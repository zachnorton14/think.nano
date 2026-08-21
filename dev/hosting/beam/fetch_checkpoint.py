#!/usr/bin/env python3
"""
Pull the exact files a deployment needs out of the HuggingFace artifacts repo.

Your base config sets `artifacts.keep_local_checkpoints: 1`, so a finished SFT
run usually survives only on HuggingFace. scripts/experiment.py lays it out as

    experiments/<BASE_ID>/sft/<BASE_ID>-<SFT_SUFFIX>/checkpoints/model_XXXXXX.pt
                                                    /meta_XXXXXX.json
    experiments/<BASE_ID>/tokenizer/tokenizer.pkl

so for MODEL_TAG = Think.Unbounded-d32-v2mix-cont-pre1930-curriculum-c3-robust-v2
the base id is Think.Unbounded-d32-v2mix-cont and the suffix is the rest.

Rather than trust that layout, this lists the repo and locates the newest
complete step (model + meta) plus a tokenizer, printing what it found. Then run
export_bf16.py on the result.

    python dev/hosting/beam/fetch_checkpoint.py --out ./ckpt

Needs HF_TOKEN in the environment if the repo is private.
"""

import argparse
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from config import BASE_EXPERIMENT_ID, MODEL_TAG  # noqa: E402

DEFAULT_REPO = "jbduran/bart-experiments"


def newest_complete_step(files, prefix):
    """Highest step under `prefix` that has both a model and a meta file."""
    models, metas = {}, {}
    for path in files:
        if not path.startswith(prefix):
            continue
        name = path[len(prefix):]
        if "/" in name:
            continue
        if match := re.fullmatch(r"model_(\d{6})\.pt", name):
            models[int(match.group(1))] = path
        elif match := re.fullmatch(r"meta_(\d{6})\.json", name):
            metas[int(match.group(1))] = path
    complete = sorted(set(models) & set(metas))
    if not complete:
        return None, None, None
    step = complete[-1]
    return step, models[step], metas[step]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=DEFAULT_REPO, help="HuggingFace model repo")
    parser.add_argument("--model-tag", default=MODEL_TAG, help="SFT experiment id to serve")
    parser.add_argument("--base-experiment-id", default=BASE_EXPERIMENT_ID,
                        help="Base experiment the SFT branched from (holds the tokenizer)")
    parser.add_argument("--step", type=int, default=None, help="Step to fetch (default: newest complete)")
    parser.add_argument("--out", required=True, help="Local directory to download into")
    parser.add_argument("--list-only", action="store_true", help="Show what would be fetched, download nothing")
    args = parser.parse_args()

    from huggingface_hub import hf_hub_download, list_repo_files

    token = os.environ.get("HF_TOKEN")
    print(f"repo:      {args.repo}")
    print(f"model tag: {args.model_tag}")
    files = list_repo_files(args.repo, repo_type="model", token=token)

    sft_prefix = f"experiments/{args.base_experiment_id}/sft/{args.model_tag}/checkpoints/"
    step, model_path, meta_path = newest_complete_step(files, sft_prefix)
    if step is None:
        print(f"\nNo complete checkpoint under {sft_prefix}")
        candidates = sorted({p.rsplit("/", 1)[0] for p in files if "/checkpoints/" in p})
        print("Directories that do contain checkpoints:")
        for path in candidates[:40]:
            print(f"  {path}")
        raise SystemExit(1)

    if args.step is not None:
        if args.step > step:
            raise SystemExit(f"Step {args.step} is newer than the newest complete step {step}")
        model_path = f"{sft_prefix}model_{args.step:06d}.pt"
        meta_path = f"{sft_prefix}meta_{args.step:06d}.json"
        if model_path not in files or meta_path not in files:
            raise SystemExit(f"Step {args.step} is not complete in the repo")
        step = args.step

    # The tokenizer is uploaded per experiment; check the SFT prefix first and
    # fall back to the base experiment, which is where a reused tokenizer lands.
    tokenizer_path = None
    for prefix in (f"experiments/{args.base_experiment_id}/sft/{args.model_tag}",
                   f"experiments/{args.base_experiment_id}"):
        candidate = f"{prefix}/tokenizer/tokenizer.pkl"
        if candidate in files:
            tokenizer_path = candidate
            break
    if tokenizer_path is None:
        matches = [p for p in files if p.endswith("tokenizer/tokenizer.pkl")]
        raise SystemExit(
            "No tokenizer.pkl found for this experiment. Candidates in the repo:\n  "
            + "\n  ".join(matches[:20])
        )

    print(f"\nstep:      {step}")
    for label, path in (("model", model_path), ("meta", meta_path), ("tokenizer", tokenizer_path)):
        print(f"{label + ':':10} {path}")
    if args.list_only:
        return

    out_dir = os.path.abspath(os.path.expanduser(args.out))
    tokenizer_dir = os.path.join(out_dir, "tokenizer")
    os.makedirs(tokenizer_dir, exist_ok=True)

    print()
    for path, dest_dir in ((model_path, out_dir), (meta_path, out_dir), (tokenizer_path, tokenizer_dir)):
        print(f"downloading {os.path.basename(path)} ...", flush=True)
        local = hf_hub_download(args.repo, path, repo_type="model", token=token)
        dest = os.path.join(dest_dir, os.path.basename(path))
        if os.path.abspath(local) != dest:
            with open(local, "rb") as src, open(dest, "wb") as out:
                while chunk := src.read(1 << 24):
                    out.write(chunk)

    with open(os.path.join(out_dir, f"meta_{step:06d}.json"), "r", encoding="utf-8") as f:
        meta = json.load(f)
    print(f"\ntraining_complete: {meta.get('training_complete')}   val_bpb: {meta.get('val_bpb')}")
    print(f"model_config:      {meta.get('model_config')}")
    print(f"\nNext:\n  python {os.path.join(_HERE, 'export_bf16.py')} \\\n"
          f"      --in-dir {out_dir} \\\n"
          f"      --out-dir {out_dir}-bf16 \\\n"
          f"      --tokenizer-dir {tokenizer_dir}")


if __name__ == "__main__":
    main()
