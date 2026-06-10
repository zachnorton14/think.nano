"""
Build a local pretokenized cache from nanochat-compatible parquet shards.

The output is intentionally local-only:
  $NANOCHAT_BASE_DIR/base_data_think_tok/
    train_00000.bin ...
    val_00000.bin ...
    meta.json

Each .bin stores uint16 token ids from the trained nanochat tokenizer.
"""

import argparse
import json
import math
import os
import shutil
import time

import numpy as np
import pyarrow.parquet as pq

from nanochat.common import get_base_dir
from nanochat.dataset import DATA_DIR, list_parquet_files
from nanochat.tokenizer import get_tokenizer


def _default_output_dir():
    return os.environ.get(
        "NANOCHAT_PRETOKENIZED_DIR",
        os.path.join(get_base_dir(), "base_data_think_tok"),
    )


class TokenShardWriter:
    def __init__(self, output_dir, prefix, shard_tokens):
        self.output_dir = output_dir
        self.prefix = prefix
        self.shard_tokens = int(shard_tokens)
        self.files = []
        self.total_tokens = 0
        self.shard_index = 0
        self.current = None
        self.current_tokens = 0
        self.current_path = None

    def _open_next(self):
        filename = f"{self.prefix}_{self.shard_index:05d}.bin"
        self.current_path = os.path.join(self.output_dir, filename)
        self.current = open(self.current_path, "wb")
        self.current_tokens = 0
        self.shard_index += 1

    def _close_current(self):
        if self.current is None:
            return
        self.current.close()
        filename = os.path.basename(self.current_path)
        self.files.append({"filename": filename, "num_tokens": self.current_tokens})
        self.current = None
        self.current_path = None
        self.current_tokens = 0

    def write(self, tokens):
        if not tokens:
            return
        arr = np.asarray(tokens, dtype=np.uint16)
        offset = 0
        while offset < len(arr):
            if self.current is None:
                self._open_next()
            remaining = self.shard_tokens - self.current_tokens
            take = min(remaining, len(arr) - offset)
            arr[offset:offset + take].tofile(self.current)
            self.current_tokens += take
            self.total_tokens += take
            offset += take
            if self.current_tokens >= self.shard_tokens:
                self._close_current()

    def close(self):
        self._close_current()


def _existing_cache_satisfies(output_dir, target_tokens, val_tokens):
    meta_path = os.path.join(output_dir, "meta.json")
    if not os.path.exists(meta_path):
        return False
    with open(meta_path, "r") as f:
        meta = json.load(f)
    if meta.get("dtype") != "uint16":
        return False
    if (
        target_tokens > 0
        and meta.get("train_tokens", 0) < target_tokens
        and not meta.get("train_source_exhausted", False)
    ):
        return False
    if val_tokens > 0 and meta.get("val_tokens", 0) < val_tokens:
        return False
    for split in ("train", "val"):
        for entry in meta.get(f"{split}_files", []):
            if not os.path.exists(os.path.join(output_dir, entry["filename"])):
                return False
    return True


def _iter_row_group_texts(parquet_paths):
    for path in parquet_paths:
        pf = pq.ParquetFile(path)
        for rg_idx in range(pf.num_row_groups):
            texts = pf.read_row_group(rg_idx, columns=["text"]).column("text").to_pylist()
            yield path, rg_idx, texts


def _write_split(split, parquet_paths, writer, tokenizer, max_tokens, tokenizer_threads, tokenizer_batch_size):
    bos_token = tokenizer.get_bos_token_id()
    started = time.time()
    for path, rg_idx, texts in _iter_row_group_texts(parquet_paths):
        for start in range(0, len(texts), tokenizer_batch_size):
            batch = texts[start:start + tokenizer_batch_size]
            token_lists = tokenizer.encode(batch, prepend=bos_token, num_threads=tokenizer_threads)
            for tokens in token_lists:
                if max_tokens > 0:
                    remaining = max_tokens - writer.total_tokens
                    if remaining <= 0:
                        writer.close()
                        return
                    if len(tokens) > remaining:
                        tokens = tokens[:remaining]
                writer.write(tokens)
        elapsed = max(time.time() - started, 1e-6)
        print(
            f"{split}: {writer.total_tokens:,} tokens | "
            f"{os.path.basename(path)} rg={rg_idx} | "
            f"{writer.total_tokens / elapsed:,.0f} tok/s",
            flush=True,
        )
    writer.close()


def main():
    parser = argparse.ArgumentParser(description="Pretokenize local nanochat parquet shards")
    parser.add_argument("--output-dir", type=str, default=_default_output_dir(), help="output token cache directory")
    parser.add_argument("--data-dir", type=str, default=None, help="input parquet directory")
    parser.add_argument("--tokenizer-dir", type=str, default=None, help="trained tokenizer directory")
    parser.add_argument("--source-dataset-repo", type=str, default=None, help="dataset identifier recorded in meta.json")
    parser.add_argument("--source-revision", type=str, default=None, help="dataset revision recorded in meta.json")
    parser.add_argument("--target-tokens", type=int, default=-1, help="train tokens to write (-1 = all local train shards)")
    parser.add_argument("--val-tokens", type=int, default=20_000_000, help="validation tokens to write")
    parser.add_argument("--shard-tokens", type=int, default=100_000_000, help="tokens per output .bin shard")
    parser.add_argument("--tokenizer-threads", type=int, default=8, help="threads passed to tokenizer batch encoding")
    parser.add_argument("--tokenizer-batch-size", type=int, default=128, help="texts per tokenizer batch")
    parser.add_argument("--force", action="store_true", help="rebuild even when an adequate cache already exists")
    args = parser.parse_args()

    assert args.shard_tokens > 0
    assert args.val_tokens >= 0
    assert args.target_tokens == -1 or args.target_tokens > 0

    if not args.force and _existing_cache_satisfies(args.output_dir, args.target_tokens, args.val_tokens):
        print(f"Existing pretokenized cache satisfies request: {args.output_dir}")
        return

    data_dir = args.data_dir or os.environ.get("NANOCHAT_DATA_DIR") or DATA_DIR
    parquet_paths = list_parquet_files(data_dir=data_dir)
    assert len(parquet_paths) >= 2, f"Need train shards plus validation in {data_dir}."
    train_paths = parquet_paths[:-1]
    val_paths = parquet_paths[-1:]

    tokenizer = get_tokenizer(tokenizer_dir=args.tokenizer_dir)
    vocab_size = tokenizer.get_vocab_size()
    assert vocab_size <= np.iinfo(np.uint16).max + 1, f"vocab_size={vocab_size} does not fit uint16"

    if os.path.exists(args.output_dir):
        shutil.rmtree(args.output_dir)
    os.makedirs(args.output_dir, exist_ok=True)

    train_writer = TokenShardWriter(args.output_dir, "train", args.shard_tokens)
    val_writer = TokenShardWriter(args.output_dir, "val", args.shard_tokens)

    print(f"Writing pretokenized cache to {args.output_dir}")
    print(f"Train target: {'all local shards' if args.target_tokens == -1 else f'{args.target_tokens:,} tokens'}")
    print(f"Val target:   {args.val_tokens:,} tokens")
    print(f"Shard size:   {args.shard_tokens:,} tokens")

    _write_split("train", train_paths, train_writer, tokenizer, args.target_tokens, args.tokenizer_threads, args.tokenizer_batch_size)
    _write_split("val", val_paths, val_writer, tokenizer, args.val_tokens, args.tokenizer_threads, args.tokenizer_batch_size)

    train_writer.close()
    val_writer.close()

    meta = {
        "source_dataset_repo": args.source_dataset_repo,
        "source_revision": args.source_revision,
        "source_data_dir": data_dir,
        "tokenizer_dir": args.tokenizer_dir or os.environ.get("NANOCHAT_TOKENIZER_DIR"),
        "output_dir": args.output_dir,
        "dtype": "uint16",
        "vocab_size": vocab_size,
        "shard_tokens": args.shard_tokens,
        "requested_train_tokens": args.target_tokens,
        "requested_val_tokens": args.val_tokens,
        "train_tokens": train_writer.total_tokens,
        "val_tokens": val_writer.total_tokens,
        "train_source_exhausted": (
            args.target_tokens > 0 and train_writer.total_tokens < args.target_tokens
        ),
        "train_files": train_writer.files,
        "val_files": val_writer.files,
        "train_parquet_files": [os.path.basename(p) for p in train_paths],
        "val_parquet_files": [os.path.basename(p) for p in val_paths],
        "created_at_unix": math.floor(time.time()),
    }
    meta_path = os.path.join(args.output_dir, "meta.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Wrote {meta_path}")
    print(f"Train tokens: {train_writer.total_tokens:,}")
    print(f"Val tokens:   {val_writer.total_tokens:,}")


if __name__ == "__main__":
    main()
