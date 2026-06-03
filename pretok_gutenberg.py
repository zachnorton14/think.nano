"""
Pre-tokenize the Project Gutenberg corpus into flat uint16 token shards.

NOTE ON LOCATION: the source of truth for this file lives in the project root
(alongside the notebooks), NOT inside the cloned nanochat repo. The notebook's
"install" cell copies it into nanochat/scripts/ at session start so it can be
invoked as `python -m scripts.pretok_gutenberg` from inside the repo. Edit the
copy at the project root.

WHY: nanochat's default dataloader tokenizes documents on-the-fly inside the
training hot loop. That is fine for ClimbMix (short web docs) but becomes a CPU
bottleneck on Gutenberg, whose documents are entire *books* (hundreds of KB
each). Tokenizing books on the fly + the best-fit packing buffer cannot keep the
GPU fed, MFU collapses, and the d12 ETA blows past the ~110 min seen on the
"shit_gpt" ClimbMix run.

FIX: tokenize the whole corpus exactly once, here, into a flat stream of token
ids (each book prefixed with <|bos|>) and dump it to disk as uint16 .bin shards.
Training then just memory-maps these shards and reads contiguous T+1 windows with
zero tokenization in the loop -> the GPU stays saturated and the d12 run lands
back around 110-120 min.

Layout written (one directory of shards):
    <base_dir>/base_data_gutenberg_tok/
        train_000000.bin
        train_000001.bin
        ...
        val_000000.bin            # always the last shard, used as the val split
        meta.json                 # bookkeeping (dtype, token counts, etc.)

Each .bin file is a raw little-endian uint16 array of token ids, concatenated
across books. See nanochat/pretok_dataloader.py for the matching reader.

Usage (from the nanochat root):
    python -m scripts.pretok_gutenberg --target-tokens 1_500_000_000

The default target (~1.5B tokens) is just enough to cover the d12 training
horizon of ~1.32B tokens (ratio=12) plus a held-out val shard and a little
headroom, while keeping the pre-tokenization step short.
"""

import os
import json
import time
import argparse

import numpy as np

from nanochat.common import get_base_dir
from nanochat.tokenizer import get_tokenizer

# -----------------------------------------------------------------------------
# Where the source Gutenberg parquet shards live and where tokens get written.
# The notebook stages raw Gutenberg parquet shards into base_data_climbmix (it
# reuses nanochat's default data dir name), so we read from there by default.
BASE_DIR = get_base_dir()
DEFAULT_SRC_DIR = os.path.join(BASE_DIR, "base_data_climbmix")
DEFAULT_OUT_DIR = os.path.join(BASE_DIR, "base_data_gutenberg_tok")

# uint16 holds token ids up to 65535; our vocab is 32768 so this is safe and
# halves the on-disk size vs uint32.
TOKEN_DTYPE = np.uint16

# How many tokens to pack into a single output .bin shard (~100M tokens ≈ 200MB).
TOKENS_PER_SHARD = 100_000_000


def list_source_parquets(src_dir):
    import pyarrow.parquet as pq  # noqa: F401  (import here to fail fast w/ message)
    if not os.path.isdir(src_dir):
        raise FileNotFoundError(
            f"Source dir not found: {src_dir}\n"
            f"Stage the Gutenberg parquet shards there first (notebook Cell 4b)."
        )
    files = sorted(
        os.path.join(src_dir, f)
        for f in os.listdir(src_dir)
        if f.endswith(".parquet") and not f.endswith(".tmp")
    )
    if not files:
        raise FileNotFoundError(f"No .parquet files found in {src_dir}")
    return files


def iter_book_texts(parquet_paths):
    """Yield non-empty book strings from the parquet shards, one row at a time."""
    import pyarrow.parquet as pq
    for path in parquet_paths:
        pf = pq.ParquetFile(path)
        # Gutenberg shards written by the notebook use the column name 'text'.
        col = "text"
        for rg_idx in range(pf.num_row_groups):
            table = pf.read_row_group(rg_idx, columns=[col])
            for text in table.column(col).to_pylist():
                if text:
                    t = text.strip()
                    if t:
                        yield t


class ShardWriter:
    """Buffers token ids and flushes fixed-size uint16 .bin shards to disk."""

    def __init__(self, out_dir, prefix, tokens_per_shard):
        self.out_dir = out_dir
        self.prefix = prefix
        self.tokens_per_shard = tokens_per_shard
        self.buf = []           # list of np.uint16 arrays not yet flushed
        self.buf_len = 0        # number of tokens currently buffered
        self.shard_idx = 0
        self.total_tokens = 0
        self.paths = []

    def add(self, ids):
        arr = np.asarray(ids, dtype=TOKEN_DTYPE)
        self.buf.append(arr)
        self.buf_len += arr.size
        self.total_tokens += arr.size
        while self.buf_len >= self.tokens_per_shard:
            self._flush_one(self.tokens_per_shard)

    def _flush_one(self, n):
        """Write exactly n tokens from the front of the buffer to a new shard."""
        flat = np.concatenate(self.buf) if len(self.buf) > 1 else self.buf[0]
        out, rest = flat[:n], flat[n:]
        path = os.path.join(self.out_dir, f"{self.prefix}_{self.shard_idx:06d}.bin")
        tmp = path + ".tmp"
        out.tofile(tmp)
        os.replace(tmp, path)
        self.paths.append(path)
        self.shard_idx += 1
        self.buf = [rest] if rest.size else []
        self.buf_len = rest.size

    def flush_remainder(self):
        """Write whatever is left as a final (possibly smaller) shard."""
        if self.buf_len > 0:
            self._flush_one(self.buf_len)


def main():
    parser = argparse.ArgumentParser(description="Pre-tokenize Gutenberg into uint16 token shards")
    parser.add_argument("--src-dir", type=str, default=DEFAULT_SRC_DIR,
                        help="dir of source Gutenberg .parquet shards")
    parser.add_argument("--out-dir", type=str, default=DEFAULT_OUT_DIR,
                        help="dir to write token .bin shards into")
    parser.add_argument("--target-tokens", type=int, default=1_500_000_000,
                        help="stop after writing ~this many TRAIN tokens (-1 = use all data)")
    parser.add_argument("--val-tokens", type=int, default=20_000_000,
                        help="number of tokens to reserve for the held-out val shard")
    parser.add_argument("--tokens-per-shard", type=int, default=TOKENS_PER_SHARD,
                        help="tokens per output .bin shard")
    parser.add_argument("--tokenizer-threads", type=int, default=8,
                        help="threads for batched tokenizer.encode")
    parser.add_argument("--encode-batch", type=int, default=128,
                        help="how many books to feed the tokenizer per encode() call")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    # Re-run safe: if a completed run already wrote meta.json, skip.
    meta_path = os.path.join(args.out_dir, "meta.json")
    if os.path.exists(meta_path):
        meta = json.load(open(meta_path))
        if meta.get("complete"):
            print(f"Already complete: {meta['total_tokens']:,} tokens "
                  f"({meta['num_train_shards']} train + 1 val shard) in {args.out_dir}")
            return
    # Otherwise clear any partial output from an aborted run.
    for f in os.listdir(args.out_dir):
        if f.endswith(".bin") or f.endswith(".bin.tmp"):
            os.remove(os.path.join(args.out_dir, f))

    tokenizer = get_tokenizer()
    bos = tokenizer.get_bos_token_id()
    print(f"Tokenizer vocab size: {tokenizer.get_vocab_size():,} | BOS id: {bos}")

    src_paths = list_source_parquets(args.src_dir)
    print(f"Found {len(src_paths)} source parquet shards in {args.src_dir}")

    # We write the val shard first (carved off the front of the stream), then
    # the train shards. Keeping val separate guarantees no train/val overlap.
    target_train = float("inf") if args.target_tokens < 0 else args.target_tokens
    total_target = target_train + args.val_tokens

    val_writer = ShardWriter(args.out_dir, "val", args.val_tokens)
    train_writer = ShardWriter(args.out_dir, "train", args.tokens_per_shard)

    t0 = time.time()
    written = 0           # total tokens emitted (val + train)
    n_books = 0
    batch = []

    def encode_and_route(text_batch):
        nonlocal written, n_books
        token_lists = tokenizer.encode(text_batch, prepend=bos,
                                       num_threads=args.tokenizer_threads)
        for ids in token_lists:
            n_books += 1
            # Fill the val shard first, then everything else goes to train.
            if val_writer.total_tokens < args.val_tokens:
                room = args.val_tokens - val_writer.total_tokens
                if len(ids) <= room:
                    val_writer.add(ids)
                else:
                    val_writer.add(ids[:room])
                    train_writer.add(ids[room:])
            else:
                train_writer.add(ids)
            written = val_writer.total_tokens + train_writer.total_tokens

    for text in iter_book_texts(src_paths):
        batch.append(text)
        if len(batch) >= args.encode_batch:
            encode_and_route(batch)
            batch = []
            if n_books % (args.encode_batch * 20) == 0:
                rate = written / max(time.time() - t0, 1e-9)
                print(f"  books={n_books:,}  tokens={written:,}  "
                      f"({rate/1e6:.2f}M tok/s)  elapsed={time.time()-t0:.0f}s")
        if written >= total_target:
            break
    # tokenize any trailing partial batch (only if we still need tokens)
    if batch and written < total_target:
        encode_and_route(batch)

    # Make sure the val shard is complete; if the corpus was too small to fill it,
    # we still flush whatever we have so training has *a* val split.
    val_writer.flush_remainder()
    train_writer.flush_remainder()

    meta = {
        "complete": True,
        "dtype": "uint16",
        "bos_token_id": int(bos),
        "vocab_size": int(tokenizer.get_vocab_size()),
        "total_tokens": int(val_writer.total_tokens + train_writer.total_tokens),
        "train_tokens": int(train_writer.total_tokens),
        "val_tokens": int(val_writer.total_tokens),
        "num_train_shards": len(train_writer.paths),
        "num_val_shards": len(val_writer.paths),
        "tokens_per_shard": int(args.tokens_per_shard),
        "num_books": int(n_books),
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    dt = time.time() - t0
    print()
    print(f"Done in {dt:.0f}s")
    print(f"  books tokenized : {n_books:,}")
    print(f"  train tokens    : {train_writer.total_tokens:,} "
          f"across {len(train_writer.paths)} shards")
    print(f"  val tokens      : {val_writer.total_tokens:,} "
          f"across {len(val_writer.paths)} shard(s)")
    print(f"  throughput      : {written/max(dt,1e-9)/1e6:.2f}M tok/s")
    print(f"  output dir      : {args.out_dir}")


if __name__ == "__main__":
    main()
