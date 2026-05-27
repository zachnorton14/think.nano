"""
Optional post-pass global shuffle for the institutional-books shards.

The streaming script (`dev/repackage_institutional_books.py`) applies topic-balanced
per-shard mixing during write, which already gives a strong diversity baseline.
This script does a *global* random shuffle across all train shards as an
additional pass — for the strictest guarantee that any consecutive run of
output rows is uncorrelated with source-archive order.

Approach:
  1. Find all input shards in --input-dir. The last lexicographic shard is the
     val shard (per nanochat convention); we preserve it untouched.
  2. Build a global pointer list (shard_idx, row_idx) covering ALL train rows.
  3. Shuffle the pointer list with the given seed.
  4. Process pointers in CHUNK_SIZE batches. Within each batch, sort pointers
     by shard_idx for cache-friendly reads (an LRU cache keeps recently-read
     shards' text columns in memory), then re-permute fetched texts back to
     the shuffled order.
  5. Write output shards with the same nanochat-compatible format (single
     `text` column, ZSTD-3, configurable row_group_size).
  6. Append the val shard last so nanochat's last-lexicographic = val
     convention is preserved.

Usage:
    python dev/shuffle_book_shards.py \
        --input-dir  $NANOCHAT_BASE_DIR/base_data_books \
        --output-dir $NANOCHAT_BASE_DIR/base_data_books_shuffled \
        --seed 42

Runtime: ~2× I/O over the filtered corpus (read once + write once). For ~50GB
of filtered text on Colab Pro+ Drive, expect 1-2 hours.

This script is OPTIONAL. The streaming script's topic-balanced output is
already well-diversified for most use cases.
"""

import argparse
import glob
import json
import os
import random
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq


def list_input_shards(input_dir):
    """Return sorted list of parquet shards. Last is val (preserved untouched)."""
    paths = sorted(glob.glob(os.path.join(input_dir, "shard_*.parquet")))
    if not paths:
        raise SystemExit(f"No shard_*.parquet files found in {input_dir}")
    return paths


def write_shard(output_dir, shard_index, docs, row_group_size):
    filename = f"shard_{shard_index:05d}.parquet"
    final_path = os.path.join(output_dir, filename)
    tmp_path = final_path + ".tmp"
    table = pa.Table.from_pydict({"text": docs})
    pq.write_table(
        table, tmp_path,
        row_group_size=row_group_size,
        use_dictionary=False,
        compression="zstd",
        compression_level=3,
        write_statistics=False,
    )
    os.replace(tmp_path, final_path)
    return filename


class ShardLRUCache:
    """In-memory cache of input shard text columns. Bounded to `max_cache` entries."""
    def __init__(self, shard_paths, max_cache=4):
        self.shard_paths = shard_paths
        self.max_cache = max_cache
        self.cache: "OrderedDict[int, list[str]]" = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get_text(self, shard_idx, row_idx):
        if shard_idx in self.cache:
            self.cache.move_to_end(shard_idx)
            self.hits += 1
        else:
            self.misses += 1
            if len(self.cache) >= self.max_cache:
                self.cache.popitem(last=False)  # evict oldest
            table = pq.read_table(self.shard_paths[shard_idx], columns=["text"])
            self.cache[shard_idx] = table.column("text").to_pylist()
        return self.cache[shard_idx][row_idx]

    def hit_rate(self):
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


def build_pointer_list(train_shards):
    """Pass 1: open each shard's metadata, build (shard_idx, row_idx) pointer list."""
    pointers = []
    per_shard_rows = []
    for i, p in enumerate(train_shards):
        pf = pq.ParquetFile(p)
        n = pf.metadata.num_rows
        per_shard_rows.append(n)
        pointers.extend((i, r) for r in range(n))
    return pointers, per_shard_rows


def shuffle_and_write(input_dir, output_dir, seed, chars_per_shard, row_group_size,
                     chunk_size, cache_size):
    os.makedirs(output_dir, exist_ok=True)

    all_shards = list_input_shards(input_dir)
    if len(all_shards) < 2:
        raise SystemExit(
            f"Need at least 2 input shards (train + val), found {len(all_shards)}."
        )

    val_shard_path = all_shards[-1]
    train_shards = all_shards[:-1]
    print(f"Input: {len(train_shards)} train shards + 1 val shard ({os.path.basename(val_shard_path)})")

    # Pass 1
    print("Pass 1: building pointer list (reading shard metadata)...")
    t0 = time.time()
    pointers, per_shard_rows = build_pointer_list(train_shards)
    print(f"  built {len(pointers):,} pointers across {len(train_shards)} shards "
          f"in {time.time()-t0:.1f}s "
          f"(rows/shard min={min(per_shard_rows)} max={max(per_shard_rows)})")

    # Shuffle
    rng = random.Random(seed)
    print(f"Shuffling pointer list (seed={seed})...")
    rng.shuffle(pointers)

    # Pass 2: chunked fetch with cache
    print(f"Pass 2: fetching + writing (chunk_size={chunk_size:,}, "
          f"cache_size={cache_size}, chars_per_shard={chars_per_shard:,})...")
    cache = ShardLRUCache(train_shards, max_cache=cache_size)
    out_idx = 0
    buf_texts = []
    buf_chars = 0
    t_start = time.time()
    t_last_log = t_start

    for chunk_start in range(0, len(pointers), chunk_size):
        chunk = pointers[chunk_start:chunk_start + chunk_size]
        # Sort within the chunk by shard_idx for cache hit rate; remember
        # original position so we can re-permute back to shuffled order.
        indexed = sorted(enumerate(chunk), key=lambda x: x[1][0])
        fetched = [None] * len(chunk)
        for original_pos, (shard_idx, row_idx) in indexed:
            fetched[original_pos] = cache.get_text(shard_idx, row_idx)

        # Drain into output buffer in shuffled order
        for t in fetched:
            buf_texts.append(t)
            buf_chars += len(t)
            if buf_chars >= chars_per_shard:
                fname = write_shard(output_dir, out_idx, buf_texts, row_group_size)
                elapsed = time.time() - t_start
                pct = 100.0 * (chunk_start + len(chunk)) / len(pointers)
                print(f"  [{elapsed:6.0f}s] wrote {fname} | docs={len(buf_texts):,} "
                      f"chars={buf_chars:,} | cache hit rate={cache.hit_rate():.2%} "
                      f"| progress={pct:.1f}%")
                out_idx += 1
                buf_texts = []
                buf_chars = 0

        # Periodic progress log even without a flush
        now = time.time()
        if now - t_last_log > 30.0:
            elapsed = now - t_start
            pct = 100.0 * (chunk_start + len(chunk)) / len(pointers)
            print(f"  [{elapsed:6.0f}s] progress {pct:.1f}% "
                  f"| pointers processed={chunk_start + len(chunk):,}/{len(pointers):,} "
                  f"| cache hit rate={cache.hit_rate():.2%} | buf={len(buf_texts)} docs")
            t_last_log = now

    # Final partial train shard
    if buf_texts:
        fname = write_shard(output_dir, out_idx, buf_texts, row_group_size)
        print(f"  wrote final train shard {fname} | docs={len(buf_texts):,} chars={buf_chars:,}")
        out_idx += 1
        buf_texts = []
        buf_chars = 0

    # Val shard: rewrite untouched (preserves the reservoir-sampled val from upstream)
    print(f"Copying val shard {os.path.basename(val_shard_path)} as new last shard...")
    val_table = pq.read_table(val_shard_path)
    val_docs = val_table.column("text").to_pylist()
    val_fname = write_shard(output_dir, out_idx, val_docs, row_group_size)
    print(f"  wrote val shard {val_fname} | docs={len(val_docs):,}")
    out_idx += 1

    # Manifest
    manifest = {
        "source_input_dir": input_dir,
        "operation": "global_shuffle",
        "seed": seed,
        "input_train_shards": len(train_shards),
        "input_total_rows": sum(per_shard_rows),
        "output_shards": out_idx,
        "chars_per_shard": chars_per_shard,
        "row_group_size": row_group_size,
        "cache_hit_rate_final": cache.hit_rate(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(os.path.join(output_dir, "shuffle_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    elapsed = time.time() - t_start
    print(f"\n=== Done ===")
    print(f"Input shards: {len(all_shards)} ({len(train_shards)} train + 1 val)")
    print(f"Output shards: {out_idx} (last = val, preserved untouched)")
    print(f"Total rows shuffled: {sum(per_shard_rows):,}")
    print(f"Cache hit rate: {cache.hit_rate():.2%}")
    print(f"Wall-clock: {elapsed/60:.1f}m")


def parse_args():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--input-dir", type=str, required=True,
                   help="Directory containing shard_*.parquet files (last lexicographic = val)")
    p.add_argument("--output-dir", type=str, required=True,
                   help="Where to write the shuffled shards (created if missing)")
    p.add_argument("--seed", type=int, default=42, help="Shuffle seed (default: 42)")
    p.add_argument("--chars-per-shard", type=int, default=250_000_000,
                   help="Target chars per output shard (default: 250M)")
    p.add_argument("--row-group-size", type=int, default=64,
                   help="Output parquet row group size (default: 64)")
    p.add_argument("--chunk-size", type=int, default=4096,
                   help="Pointers processed per cache-friendly batch (default: 4096)")
    p.add_argument("--cache-size", type=int, default=4,
                   help="Number of input shards held in memory at once (default: 4)")
    return p.parse_args()


def main():
    args = parse_args()
    shuffle_and_write(
        args.input_dir, args.output_dir, args.seed,
        args.chars_per_shard, args.row_group_size,
        args.chunk_size, args.cache_size,
    )


if __name__ == "__main__":
    main()
