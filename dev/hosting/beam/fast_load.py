"""
A serving-only model loader that skips the work `build_model` does for training.

`nanochat.checkpoint_manager.build_model` follows the standard nanochat recipe:

    with torch.device("meta"): model = GPT(config)
    model.to_empty(device=device)     # allocates every parameter, fp32, on GPU
    model.init_weights()              # random-initialises 2.8B parameters
    model.load_state_dict(..., assign=True)   # throws all of that away

That is correct, and for training it is what you want, because `init_weights`
is where the initialisation scheme lives. For serving it is pure waste, and on a
d32 it is expensive waste:

  * `to_empty` allocates all 2.82B parameters at their *declared* dtypes, which
    are fp32 at that point -- roughly 10.5 GiB of VRAM;
  * `init_weights` then runs normal_/uniform_ kernels across all of them;
  * `load_state_dict(assign=True)` replaces every one of those tensors with the
    checkpoint's, freeing the storage that was just filled.

So the cold start pays ~10.5 GiB of allocation plus 2.8B parameters of RNG for
nothing, and peak VRAM during load is ~16 GiB instead of ~5.5 GiB.

This loader assigns the checkpoint's tensors straight onto the meta model and
then materialises the only things `init_weights` produces that are *not* in the
state dict: the rotary cos/sin buffers, which are registered `persistent=False`.

test_export.py asserts this produces a model identical to the build_model path.
"""

import json
import os
import time

import torch

from nanochat.checkpoint_manager import (
    _patch_missing_config_keys,
    _patch_missing_keys,
    find_last_step,
)
from nanochat.gpt import GPT, GPTConfig
from nanochat.tokenizer import get_tokenizer


def load_model_fast(checkpoint_dir, device, step=None, tokenizer_dir=None, verbose=True):
    """Build a ready-to-serve model, tokenizer and metadata from a checkpoint dir.

    Signature-compatible with `load_model_from_checkpoint_dir(..., phase="eval")`.
    Returns (model, tokenizer, meta_data).
    """
    if step is None:
        step = find_last_step(checkpoint_dir)

    timings = {}

    def mark(label, t0):
        timings[label] = time.time() - t0
        if verbose:
            print(f"[load] {label}: {timings[label]:.2f}s")

    # 1) Read the weights straight onto the target device. One copy, no CPU
    #    staging, no intermediate fp32 allocation.
    t0 = time.time()
    model_path = os.path.join(checkpoint_dir, f"model_{step:06d}.pt")
    model_data = torch.load(model_path, map_location=device)
    model_data = {k.removeprefix("_orig_mod."): v for k, v in model_data.items()}
    mark("read weights", t0)

    with open(os.path.join(checkpoint_dir, f"meta_{step:06d}.json"), "r", encoding="utf-8") as f:
        meta_data = json.load(f)

    model_config_kwargs = meta_data["model_config"]
    _patch_missing_config_keys(model_config_kwargs)
    model_config = GPTConfig(**model_config_kwargs)
    _patch_missing_keys(model_data, model_config)

    # 2) Shapes only -- no storage is allocated for anything here.
    t0 = time.time()
    with torch.device("meta"):
        model = GPT(model_config)
    # assign=True swaps the checkpoint's tensors in as the parameters themselves,
    # rather than copying into pre-allocated storage that does not exist.
    model.load_state_dict(model_data, strict=True, assign=True)
    mark("assign parameters", t0)

    # 3) cos/sin are registered persistent=False, so they are absent from the
    #    state dict and are still meta tensors at this point. init_weights() is
    #    where they would normally be built; build just them.
    t0 = time.time()
    head_dim = model_config.n_embd // model_config.n_head
    cos, sin = model._precompute_rotary_embeddings(
        model.rotary_seq_len, head_dim, device=device
    )
    model.cos, model.sin = cos, sin
    mark("rotary buffers", t0)

    assert not any(p.is_meta for p in model.parameters()), "a parameter was left on meta"
    assert not model.cos.is_meta and not model.sin.is_meta
    model.eval()

    t0 = time.time()
    tokenizer = get_tokenizer(tokenizer_dir=tokenizer_dir)
    mark("tokenizer", t0)
    assert tokenizer.get_vocab_size() == model_config_kwargs["vocab_size"], (
        f"Tokenizer vocab size {tokenizer.get_vocab_size()} does not match model "
        f"config vocab size {model_config_kwargs['vocab_size']}"
    )

    if verbose:
        allocated = torch.cuda.memory_allocated() / 1024 ** 3 if torch.cuda.is_available() else 0
        peak = torch.cuda.max_memory_allocated() / 1024 ** 3 if torch.cuda.is_available() else 0
        print(f"[load] total {sum(timings.values()):.2f}s, "
              f"{allocated:.2f} GiB resident, {peak:.2f} GiB peak")

    return model, tokenizer, meta_data
