#!/usr/bin/env python3
"""
Export a serving checkpoint: drop optimizer state, cast the big weights to bf16.

Why this is lossless for inference
----------------------------------
`nanochat.gpt.Linear.forward` does `F.linear(x, self.weight.to(dtype=x.dtype))`,
and every embedding output is cast with `.to(COMPUTE_DTYPE)` / `.to(x.dtype)`.
On a CUDA box with COMPUTE_DTYPE == bfloat16, every weight of rank >= 2 is
therefore *already* rounded to bf16 on every forward pass. Storing those tensors
as bf16 does the rounding once, at export time, instead of once per token. The
served logits are bit-identical (see test_export.py).

The rank < 2 parameters are the exception. `resid_lambdas` and `x0_lambdas` are
multiplied into the residual stream directly (gpt.py: `self.resid_lambdas[i] * x`)
with no cast, so their stored precision is the precision that is actually used.
They total a few hundred bytes, so they stay fp32.

Usage
-----
    python -m dev.hosting.export_bf16 \
        --in-dir  ~/.cache/nanochat/chatsft_checkpoints/d32 \
        --out-dir ~/.cache/nanochat/serving/d32-bf16 \
        --tokenizer-dir ~/.cache/nanochat/tokenizer

Add --step to pin an exact step (default: the highest one present).
The output directory is laid out exactly like an ordinary nanochat checkpoint
directory, so `load_model_from_checkpoint_dir` reads it with no special casing.
"""

import argparse
import glob
import json
import os
import shutil

import torch

# Deliberately NOT importing anything from nanochat. `find_last_step` lives in
# nanochat.checkpoint_manager, but importing that module pulls in nanochat.gpt
# and nanochat.tokenizer, and therefore tokenizers, rustbpe and tiktoken -- the
# whole tokenizer stack, to use five lines of glob. This script is the pure-CPU
# step that should run on any box that has the checkpoint, so it needs torch and
# nothing else. The reimplementation below is the same rule as the original.


def find_last_step(checkpoint_dir):
    """Highest N for which model_N.pt exists. Mirrors nanochat's version."""
    files = glob.glob(os.path.join(checkpoint_dir, "model_*.pt"))
    if not files:
        raise FileNotFoundError(f"No checkpoints found in {checkpoint_dir}")
    return int(max(os.path.basename(f).split("_")[-1].split(".")[0] for f in files))

# Files the server needs beside the weights. token_bytes.pt is deliberately not
# copied: it is only read by nanochat.loss_eval during training.
TOKENIZER_FILES = ("tokenizer.pkl",)


def human(nbytes):
    return f"{nbytes / 1024 ** 3:.2f} GiB"


def dtype_breakdown(state_dict):
    """Bytes per dtype, so the before/after report shows where the size went."""
    totals = {}
    for tensor in state_dict.values():
        key = str(tensor.dtype).removeprefix("torch.")
        totals[key] = totals.get(key, 0) + tensor.numel() * tensor.element_size()
    return dict(sorted(totals.items(), key=lambda kv: -kv[1]))


def cast_state_dict(state_dict, dtype=torch.bfloat16, consume=False):
    """Cast rank >= 2 floating point tensors; leave scalars/vectors alone.

    Rank >= 2 is exactly the set of Linear/Embedding weights, i.e. the tensors
    the forward pass already casts to the activation dtype. Rank < 2 is the set
    of per-layer scalars that multiply activations directly.

    `consume=True` empties `state_dict` as it goes, freeing each fp32 tensor as
    soon as its bf16 copy exists. That is the difference between needing ~14 GiB
    of RAM for a d32 and needing ~9 GiB, which is the difference between running
    this on a laptop and not.
    """
    out, cast_keys, kept_keys = {}, [], []
    for key in list(state_dict.keys()):
        tensor = state_dict.pop(key) if consume else state_dict[key]
        if tensor.is_floating_point() and tensor.dim() >= 2 and tensor.dtype != dtype:
            out[key] = tensor.to(dtype)
            cast_keys.append(key)
        else:
            out[key] = tensor
            kept_keys.append(key)
        del tensor
    return out, cast_keys, kept_keys


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in-dir", required=True, help="Checkpoint dir holding model_XXXXXX.pt + meta_XXXXXX.json")
    parser.add_argument("--out-dir", required=True, help="Destination dir for the serving checkpoint")
    parser.add_argument("--step", type=int, default=None, help="Step to export (default: highest present)")
    parser.add_argument("--tokenizer-dir", default=None, help="Tokenizer dir to copy into <out-dir>/tokenizer")
    parser.add_argument("--dtype", default="bfloat16", choices=["bfloat16", "float16"], help="Storage dtype for rank>=2 weights")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing export")
    args = parser.parse_args()

    dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16}[args.dtype]
    in_dir = os.path.expanduser(args.in_dir)
    out_dir = os.path.expanduser(args.out_dir)
    step = args.step if args.step is not None else find_last_step(in_dir)

    model_path = os.path.join(in_dir, f"model_{step:06d}.pt")
    meta_path = os.path.join(in_dir, f"meta_{step:06d}.json")
    for path in (model_path, meta_path):
        if not os.path.exists(path):
            raise SystemExit(f"Missing {path}")

    out_model_path = os.path.join(out_dir, f"model_{step:06d}.pt")
    if os.path.exists(out_model_path) and not args.force:
        raise SystemExit(f"{out_model_path} already exists (pass --force to overwrite)")

    print(f"Reading step {step} from {in_dir}")
    state_dict = torch.load(model_path, map_location="cpu")
    # torch.compile prefixes every key with _orig_mod. -- strip it here so the
    # served file is clean, exactly as checkpoint_manager.build_model would.
    state_dict = {k.removeprefix("_orig_mod."): v for k, v in state_dict.items()}
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    # consume=True frees each fp32 tensor as its bf16 copy is made, so peak RAM
    # is roughly the size of the original file rather than 1.6x it.
    before = dtype_breakdown(state_dict)
    exported, cast_keys, kept_keys = cast_state_dict(state_dict, dtype, consume=True)
    after = dtype_breakdown(exported)
    del state_dict

    print(f"\nCast to {args.dtype}: {len(cast_keys)} tensors (rank >= 2)")
    print(f"Left as-is:          {len(kept_keys)} tensors -> {', '.join(kept_keys) or '(none)'}")
    print("\n  before:", {k: human(v) for k, v in before.items()}, "=", human(sum(before.values())))
    print("  after: ", {k: human(v) for k, v in after.items()}, "=", human(sum(after.values())))

    os.makedirs(out_dir, exist_ok=True)
    tmp_path = out_model_path + ".tmp"
    torch.save(exported, tmp_path)
    os.replace(tmp_path, out_model_path)

    meta["export"] = {
        "source_dir": os.path.abspath(in_dir),
        "source_step": step,
        "storage_dtype": args.dtype,
        "cast_tensors": len(cast_keys),
        "kept_fp32_tensors": kept_keys,
        "optimizer_state_stripped": True,
    }
    with open(os.path.join(out_dir, f"meta_{step:06d}.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    if args.tokenizer_dir:
        tok_src = os.path.expanduser(args.tokenizer_dir)
        tok_dst = os.path.join(out_dir, "tokenizer")
        os.makedirs(tok_dst, exist_ok=True)
        for name in TOKENIZER_FILES:
            src = os.path.join(tok_src, name)
            if not os.path.exists(src):
                raise SystemExit(f"Tokenizer file not found: {src}")
            shutil.copy2(src, os.path.join(tok_dst, name))
        print(f"\nCopied {', '.join(TOKENIZER_FILES)} -> {tok_dst}")

    # Verify what we wrote rather than what we think we wrote: reload from disk
    # and confirm the tensors round-tripped exactly.
    reloaded = torch.load(out_model_path, map_location="cpu")
    assert reloaded.keys() == exported.keys(), "Key set changed on the round trip"
    for key, tensor in exported.items():
        got = reloaded[key]
        assert got.dtype == tensor.dtype and got.shape == tensor.shape, f"{key}: dtype/shape drift"
        assert torch.equal(got, tensor), f"{key}: values changed on the round trip"

    on_disk = os.path.getsize(out_model_path)
    original = os.path.getsize(model_path)
    print(f"\nWrote {out_model_path}")
    print(f"  {human(original)} -> {human(on_disk)} ({100 * (1 - on_disk / original):.0f}% smaller)")
    print(f"\nServe with: --checkpoint-dir {out_dir} --tokenizer-dir {out_dir}/tokenizer --step {step}")


if __name__ == "__main__":
    main()
