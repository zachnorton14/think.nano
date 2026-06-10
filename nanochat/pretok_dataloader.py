"""
Pretokenized dataloaders for base pretraining.

These loaders consume flat uint16 token streams produced by scripts.pretok_think.
They avoid all tokenizer calls in the training loop while preserving the
(x, y, state_dict) contract used by base_train checkpoints.
"""

import json
import os

import numpy as np
import torch

from nanochat.common import get_base_dir, get_dist_info


def _default_data_dir():
    return os.environ.get(
        "NANOCHAT_PRETOKENIZED_DIR",
        os.path.join(get_base_dir(), "base_data_think_tok"),
    )


def _load_split_files(split, data_dir):
    assert split in ("train", "val"), "split must be 'train' or 'val'"
    meta_path = os.path.join(data_dir, "meta.json")
    assert os.path.exists(meta_path), f"Missing pretokenized meta.json at {meta_path}. Run scripts.pretok_think first."
    with open(meta_path, "r") as f:
        meta = json.load(f)

    dtype = np.dtype(meta.get("dtype", "uint16"))
    entries = meta.get(f"{split}_files", [])
    assert entries, f"No {split} token files listed in {meta_path}"

    arrays = []
    sizes = []
    for entry in entries:
        filename = entry["filename"] if isinstance(entry, dict) else entry
        path = os.path.join(data_dir, filename)
        assert os.path.exists(path), f"Missing pretokenized shard: {path}"
        arr = np.memmap(path, mode="r", dtype=dtype)
        assert len(arr) > 0, f"Empty pretokenized shard: {path}"
        arrays.append(arr)
        sizes.append(len(arr))
    return arrays, sizes


class _TokenCursor:
    def __init__(self, arrays, sizes, file_idx=0, pos=0, epoch=1):
        self.arrays = arrays
        self.sizes = sizes
        self.file_idx = int(file_idx)
        self.pos = int(pos)
        self.epoch = int(epoch)
        self.file_idx %= len(self.arrays)
        self.pos = min(self.pos, self.sizes[self.file_idx])
        if self.pos == self.sizes[self.file_idx]:
            self._advance_file()

    def _advance_file(self):
        self.file_idx += 1
        self.pos = 0
        if self.file_idx >= len(self.arrays):
            self.file_idx = 0
            self.epoch += 1

    def skip(self, n):
        remaining = int(n)
        while remaining > 0:
            available = self.sizes[self.file_idx] - self.pos
            step = min(available, remaining)
            self.pos += step
            remaining -= step
            if self.pos >= self.sizes[self.file_idx]:
                self._advance_file()

    def read(self, n):
        out = np.empty(int(n), dtype=np.uint16)
        filled = 0
        while filled < n:
            arr = self.arrays[self.file_idx]
            available = self.sizes[self.file_idx] - self.pos
            take = min(available, n - filled)
            out[filled:filled + take] = arr[self.pos:self.pos + take]
            filled += take
            self.pos += take
            if self.pos >= self.sizes[self.file_idx]:
                self._advance_file()
        return out

    def state_dict(self):
        return {
            "file_idx": self.file_idx,
            "pos": self.pos,
            "epoch": self.epoch,
            # Backward-compatible display aliases for base_train logging.
            "pq_idx": self.file_idx,
            "rg_idx": self.pos,
        }


def pretokenized_data_loader_with_state(
    B,
    T,
    split,
    device="cuda",
    resume_state_dict=None,
    data_dir=None,
):
    data_dir = _default_data_dir() if data_dir is None else data_dir
    arrays, sizes = _load_split_files(split, data_dir)
    _, ddp_rank, _, ddp_world_size = get_dist_info()

    tokens_per_rank_batch = B * T
    read_tokens = tokens_per_rank_batch + 1

    if resume_state_dict is None:
        cursor = _TokenCursor(arrays, sizes, file_idx=0, pos=0, epoch=1)
        cursor.skip(ddp_rank * tokens_per_rank_batch)
    else:
        cursor = _TokenCursor(
            arrays,
            sizes,
            file_idx=resume_state_dict.get("file_idx", resume_state_dict.get("pq_idx", 0)),
            pos=resume_state_dict.get("pos", resume_state_dict.get("rg_idx", 0)),
            epoch=resume_state_dict.get("epoch", 1),
        )

    use_cuda = device == "cuda"
    cpu_buffer = torch.empty(read_tokens, dtype=torch.long, pin_memory=use_cuda)
    gpu_buffer = torch.empty(read_tokens, dtype=torch.long, device=device)

    while True:
        batch_np = cursor.read(read_tokens).astype(np.int64, copy=False)
        cpu_buffer.copy_(torch.from_numpy(batch_np))
        state_dict = cursor.state_dict()
        gpu_buffer.copy_(cpu_buffer, non_blocking=use_cuda)
        flat_x = gpu_buffer[:-1]
        flat_y = gpu_buffer[1:]
        yield flat_x.view(B, T), flat_y.view(B, T), state_dict
        cursor.skip((ddp_world_size - 1) * tokens_per_rank_batch)


def pretokenized_data_loader(*args, **kwargs):
    """Helper that omits state_dict from yields."""
    for inputs, targets, _ in pretokenized_data_loader_with_state(*args, **kwargs):
        yield inputs, targets
