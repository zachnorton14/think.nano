"""Import a flat Hugging Face nanochat checkpoint into experiment layout.

Several public nanochat models publish ``model_*.pt`` and ``meta_*.json`` at
repository root instead of under this fork's ``experiments/...`` hierarchy.
This command downloads only the requested checkpoint and tokenizer, records its
source revision, and makes it available as an immutable SFT parent.
"""

import argparse
import json
import os
import shutil
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

from nanochat.common import get_base_dir


def _copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument("--model-file", default="")
    parser.add_argument("--meta-file", default="")
    parser.add_argument("--tokenizer-file", default="tokenizer.pkl")
    parser.add_argument("--token-bytes-file", default="token_bytes.pt")
    parser.add_argument(
        "--architecture",
        choices=(
            "auto",
            "nanochat_legacy_2025",
            "nanochat_resformer_2026",
            "nanochat_current",
        ),
        default="auto",
    )
    parser.add_argument("--revision", default="main")
    args = parser.parse_args()

    experiment_root = Path(
        os.environ.get(
            "NANOCHAT_EXPERIMENT_ROOT",
            Path(get_base_dir()) / "experiments",
        )
    )
    root = experiment_root / args.experiment_id
    checkpoint_dir = root / "base_checkpoints"
    tokenizer_dir = root / "tokenizer"
    model_name = args.model_file or f"model_{args.step:06d}.pt"
    meta_name = args.meta_file or f"meta_{args.step:06d}.json"
    output_model = checkpoint_dir / f"model_{args.step:06d}.pt"
    output_meta = checkpoint_dir / f"meta_{args.step:06d}.json"

    marker_path = root / "external_source.json"
    required_outputs = (
        output_model,
        output_meta,
        tokenizer_dir / "tokenizer.pkl",
        tokenizer_dir / "token_bytes.pt",
    )
    if marker_path.exists() and all(
        path.exists() and path.stat().st_size > 0 for path in required_outputs
    ):
        marker = json.loads(marker_path.read_text())
        if (
            marker.get("repo_id") == args.repo_id
            and marker.get("revision") == args.revision
        ):
            print(
                f"Already imported {args.repo_id}@{args.revision} to {root}; skipping"
            )
            return

    api = HfApi(token=os.environ.get("HF_TOKEN"))
    info = api.model_info(args.repo_id, revision=args.revision)
    resolved_revision = info.sha
    source_files = {
        "model": model_name,
        "metadata": meta_name,
        "tokenizer": args.tokenizer_file,
        "token_bytes": args.token_bytes_file,
    }
    available = {sibling.rfilename for sibling in info.siblings}
    missing = sorted(set(source_files.values()) - available)
    if missing:
        raise SystemExit(f"{args.repo_id} is missing required files: {missing}")

    downloaded = {
        key: hf_hub_download(
            args.repo_id,
            filename,
            revision=resolved_revision,
            token=os.environ.get("HF_TOKEN"),
        )
        for key, filename in source_files.items()
    }
    _copy(downloaded["model"], output_model)
    _copy(downloaded["tokenizer"], tokenizer_dir / "tokenizer.pkl")
    _copy(downloaded["token_bytes"], tokenizer_dir / "token_bytes.pt")

    meta = json.loads(Path(downloaded["metadata"]).read_text())
    if int(meta.get("step", -1)) != args.step:
        raise SystemExit(
            f"Metadata step {meta.get('step')!r} does not match requested {args.step}"
        )
    if args.architecture != "auto":
        meta["model_architecture"] = args.architecture
    meta["external_source"] = {
        "repo_id": args.repo_id,
        "revision": resolved_revision,
        "files": source_files,
    }
    output_meta.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_meta.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(meta, indent=2) + "\n")
    os.replace(temporary, output_meta)
    marker_temporary = marker_path.with_suffix(".json.tmp")
    marker_temporary.write_text(json.dumps(meta["external_source"], indent=2) + "\n")
    os.replace(marker_temporary, marker_path)

    print(f"Imported {args.repo_id}@{resolved_revision}")
    print(f"Checkpoint: {output_model}")
    print(f"Metadata:   {output_meta}")
    print(f"Tokenizer:  {tokenizer_dir}")


if __name__ == "__main__":
    main()
