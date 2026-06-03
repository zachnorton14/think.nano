"""
Pre-tokenized (flat) dataloader for pretraining.

This is the fast-path counterpart to dataloader.py. Instead of tokenizing
documents on the fly inside the training loop, it reads a flat stream of token
ids that scripts/pretok_gutenberg.py already wrote to disk as uint16 .bin
shards. Because there is no tokenization (and no best-fit packing) in the hot
loop, the GPU stays fed and MFU stays high — this is what keeps the Gutenberg
d12 run near the ~110-120 min "shit_gpt" ETA.

Packing is plain GPT-style flat concatenation: the token stream (each book
already prefixed with <|bos|> at pre-tokenization time) is chopped into
contiguous windows of length T+1, where x = window[:-1], y = window[1:]. There
is no cropping and no padding — every token is trained on. Documents may span
row boundaries, which is the classic and most compute-efficient layout.

Signatures match dataloader.py exactly so base_train.py can swap loaders:
  - train loader yields (inputs, targets, state_dict)
  - val loader   yields (inputs, targets)

NOTE ON LOCATION: the source of truth for this file lives in the project root
(alongside the notebooks), NOT inside the cloned nanochat repo. The notebook's
"install" cell copies it into nanochat/nanochat/ at session start so the package
import `from nanochat.pretok_dataloader import ...` resolves. Edit the copy at
the project root.
"""

import os
import json

import numpy as np
import torch

from nanochat.common import get_dist_info, get_base_dir

DEFAULT_TOK_DIR = os.path.join(get_base_dir(), "base_data_gutenberg_tok")


def pretok_dir_exists(tok_dir=None):
    tok_dir = DEFAULT_TOK_DIR if tok_dir is None else tok_dir
    return os.path.exists(os.path.join(tok_dir, "meta.json"))


def _load_meta(tok_dir):
    meta_path = os.path.join(tok_dir, "meta.json")
    assert os.path.exists(meta_path), (
        f"No pre-tokenized data found at {tok_dir} (missing meta.json). "
        f"Run: python -m scripts.pretok_gutenberg"
    )
    return json.load(open(meta_path))


def _split_shard_paths(tok_dir, split):
    prefix = "train" if split == "train" else "val"
    files = sorted(
        os.path.join(tok_dir, f)
        for f in os.listdir(tok_dir)
        if f.startswith(prefix + "_") and f.endswith(".bin")
    )
    assert files, f"No '{prefix}_*.bin' shards found in {tok_dir}"
    return files


class _FlatTokenStream:
    """
    Concatenated, memory-mapped view over a split's .bin shards.

    Exposes a single logical 1D token array via mmap (no full load into RAM)
    and a method to copy an arbitrary [start:start+length] slice — transparently
    spanning shard boundaries — into a destination numpy buffer.
    """

    def __init__(self, shard_paths):
        self.maps = [np.memmap(p, dtype=np.uint16, mode="r") for p in shard_paths]
        self.lengths = [m.shape[0] for m in self.maps]
        # cumulative start offset of each shard within the global stream
        self.offsets = np.cumsum([0] + self.lengths)
        self.total = int(self.offsets[-1])

    def read_into(self, dst, start, length):
        """Copy stream[start:start+length] into dst[:length] (uint dtype)."""
        assert start + length <= self.total
        filled = 0
        # locate the shard containing `start`
        shard = int(np.searchsorted(self.offsets, start, side="right") - 1)
        local = start - self.offsets[shard]
        while filled < length:
            m = self.maps[shard]
            take = min(len(m) - local, length - filled)
            dst[filled:filled + take] = m[local:local + take]
            filled += take
            shard += 1
            local = 0


def pretokenized_data_loader_with_state(
    B, T, split,
    device="cuda", resume_state_dict=None,
    tok_dir=None,
):
    """
    Flat pre-tokenized loader (train variant; yields a resume state_dict).

    Each step consumes B*(T+1) tokens from the stream, sharded across DDP ranks
    by giving rank r the r-th contiguous B*(T+1) block per global step. Loops
    infinitely (multi-epoch); when the tail of the stream can't fill a full
    global batch we wrap back to the start so steps are always full.
    """
    assert split in ["train", "val"], "split must be 'train' or 'val'"
    tok_dir = DEFAULT_TOK_DIR if tok_dir is None else tok_dir
    _load_meta(tok_dir)  # validates presence; values not needed here
    _, ddp_rank, _, ddp_world_size = get_dist_info()

    stream = _FlatTokenStream(_split_shard_paths(tok_dir, split))

    row = T + 1
    tokens_per_rank_step = B * row                 # tokens one rank reads per step
    tokens_per_global_step = tokens_per_rank_step * ddp_world_size
    assert stream.total >= tokens_per_global_step, (
        f"{split} stream has {stream.total:,} tokens but a single global step "
        f"needs {tokens_per_global_step:,}. Pre-tokenize more data."
    )
    # Last valid global-step start so that all ranks get a full block.
    max_global_start = stream.total - tokens_per_global_step

    use_cuda = device == "cuda"
    # Staging buffer for this rank's flat slice, then reshaped to rows.
    np_buf = np.empty(tokens_per_rank_step, dtype=np.uint16)
    cpu_buffer = torch.empty(2 * B * T, dtype=torch.long, pin_memory=use_cuda)
    gpu_buffer = torch.empty(2 * B * T, dtype=torch.long, device=device)
    cpu_inputs = cpu_buffer[:B * T].view(B, T)
    cpu_targets = cpu_buffer[B * T:].view(B, T)
    inputs = gpu_buffer[:B * T].view(B, T)
    targets = gpu_buffer[B * T:].view(B, T)

    # Resume support: cursor counts global token position (multiple of global step).
    cursor = 0
    epoch = 1
    if resume_state_dict is not None:
        cursor = int(resume_state_dict.get("cursor", 0))
        epoch = int(resume_state_dict.get("epoch", 1))

    while True:
        global_start = cursor
        if global_start > max_global_start:
            # wrap to a fresh epoch
            cursor = 0
            epoch += 1
            global_start = 0
        rank_start = global_start + ddp_rank * tokens_per_rank_step

        stream.read_into(np_buf, rank_start, tokens_per_rank_step)
        rows = torch.from_numpy(np_buf.astype(np.int64)).view(B, row)

        cpu_inputs.copy_(rows[:, :-1])
        cpu_targets.copy_(rows[:, 1:])
        gpu_buffer.copy_(cpu_buffer, non_blocking=use_cuda)

        cursor += tokens_per_global_step
        state_dict = {"cursor": cursor, "epoch": epoch}
        yield inputs, targets, state_dict


def pretokenized_data_loader(*args, **kwargs):
    """Helper that omits the state_dict from yields (matches val loader API)."""
    for inputs, targets, _ in pretokenized_data_loader_with_state(*args, **kwargs):
        yield inputs, targets
