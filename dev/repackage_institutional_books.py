"""
Stream, filter, and repackage `institutional/institutional-books-1.0` into
nanochat-compatible parquet shards.

Filters applied (all must pass):
  - language_gen == "eng"
  - parsed year of date1_src < --year-max (default 1930)
  - ocr_score_src  > --ocr-min (default 85)
  - ocr_score_gen  > --ocr-min (default 85)
  - |ocr_score_src - ocr_score_gen| < --ocr-disagreement-max (default 15)

Output layout (drop-in compatible with nanochat/dataset.py):
  <output_dir>/
    shard_00000.parquet         # train
    shard_00001.parquet         # train
    ...
    shard_NNNNN.parquet         # val (last lexicographic shard)
    .state.json                 # resume checkpoint
    README.md                   # provenance + stats
    manifest.json               # per-shard breakdown

Each parquet: single `text` string column, ZSTD-3,
chars_per_shard=250M (matches ClimbMix's ~100MB-compressed shard target),
row_group_size=64 (smaller than ClimbMix's 1024 because per the institutional
books report each row averages ~367 pages / ~250K tokens / ~1M chars — vs
ClimbMix's ~250K char web docs. At ~1M chars/book and 250M chars/shard, a
shard holds ~250 books, so row_group_size=64 yields ~4 row groups per shard:
small enough to keep dataloader peak memory bounded when read_row_group
materializes all rows, large enough that we don't fragment shards into
single-row-group files), use_dictionary=False, write_statistics=False.

Resume:
  Re-running with the same --output-dir picks up where it left off via
  .state.json (only updated on successful shard flush, so partial shards
  are safely re-processed).

Usage:
    # Process (resumable)
    python dev/repackage_institutional_books.py \
        --output-dir $NANOCHAT_BASE_DIR/base_data_books

    # Upload only (after local processing is complete)
    python dev/repackage_institutional_books.py \
        --output-dir $NANOCHAT_BASE_DIR/base_data_books \
        --upload-only --repo-id jbduran/think-institutional-books

Requires HF_TOKEN in .env (project root) with access to the gated dataset.
"""

import argparse
import json
import os
import re
import signal
import sys
import time
from datetime import datetime, timezone

import pyarrow as pa
import pyarrow.parquet as pq
from datasets import load_dataset
from dotenv import find_dotenv, load_dotenv
from huggingface_hub import HfApi


SOURCE_DATASET = "institutional/institutional-books-1.0"
SOURCE_SPLIT = "train"
REQUIRED_COLUMNS = ("language_gen", "date1_src", "ocr_score_src", "ocr_score_gen")
STATE_FILENAME = ".state.json"
README_FILENAME = "README.md"
MANIFEST_FILENAME = "manifest.json"


# -----------------------------------------------------------------------------
# Filtering

_YEAR_RE = re.compile(r"\d{4}")


def parse_year(date_str):
    """Extract a plausible 4-digit year from a MARC date string.

    Returns int year in [1000, 2100], or None if no usable year found.
    MARC date fields can contain artifacts like '18uu', '9999', '0000'.
    """
    if date_str is None:
        return None
    m = _YEAR_RE.search(str(date_str))
    if not m:
        return None
    year = int(m.group())
    if year < 1000 or year > 2100:
        return None
    return year


def _to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def classify_row(row, year_max, ocr_min, ocr_disagreement_max):
    """Return ('pass', None) or ('reject', reason_str)."""
    if row.get("language_gen") != "eng":
        return "reject", "language"

    year = parse_year(row.get("date1_src"))
    if year is None:
        return "reject", "year_unparseable"
    if year >= year_max:
        return "reject", "year_too_recent"

    src = _to_float(row.get("ocr_score_src"))
    gen = _to_float(row.get("ocr_score_gen"))
    if src is None or gen is None:
        return "reject", "ocr_missing"
    if src <= ocr_min or gen <= ocr_min:
        return "reject", "ocr_low"
    if abs(src - gen) >= ocr_disagreement_max:
        return "reject", "ocr_disagree"

    return "pass", None


# -----------------------------------------------------------------------------
# State (resume)

def state_path(output_dir):
    return os.path.join(output_dir, STATE_FILENAME)


def load_state(output_dir):
    """Return state dict or None if no state file exists."""
    p = state_path(output_dir)
    if not os.path.exists(p):
        return None
    with open(p, "r") as f:
        return json.load(f)


def save_state_atomic(output_dir, state):
    """Atomic write via tmp + rename."""
    p = state_path(output_dir)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, p)


# -----------------------------------------------------------------------------
# Shard writing

def write_shard(output_dir, shard_index, docs, row_group_size):
    """Write a single shard. Atomic via .tmp + rename."""
    filename = f"shard_{shard_index:05d}.parquet"
    final_path = os.path.join(output_dir, filename)
    tmp_path = final_path + ".tmp"

    table = pa.Table.from_pydict({"text": docs})
    pq.write_table(
        table,
        tmp_path,
        row_group_size=row_group_size,
        use_dictionary=False,
        compression="zstd",
        compression_level=3,
        write_statistics=False,
    )
    os.replace(tmp_path, final_path)
    return filename, final_path


# -----------------------------------------------------------------------------
# Manifest + README

def update_manifest(output_dir, args, shard_records, totals):
    manifest = {
        "source_dataset": SOURCE_DATASET,
        "source_split": SOURCE_SPLIT,
        "filters": {
            "language": "eng",
            "year_max_exclusive": args.year_max,
            "ocr_min_exclusive": args.ocr_min,
            "ocr_disagreement_max_exclusive": args.ocr_disagreement_max,
        },
        "shard_config": {
            "chars_per_shard": args.chars_per_shard,
            "row_group_size": args.row_group_size,
            "compression": "zstd-3",
            "schema": "single string column named 'text'",
        },
        "shards": shard_records,
        "totals": totals,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    tmp = os.path.join(output_dir, MANIFEST_FILENAME + ".tmp")
    with open(tmp, "w") as f:
        json.dump(manifest, f, indent=2)
    os.replace(tmp, os.path.join(output_dir, MANIFEST_FILENAME))


def write_readme(output_dir, args, totals, shard_records):
    rejection_lines = "\n".join(
        f"  - `{k}`: {v:,}" for k, v in sorted(totals["rejections"].items())
    )
    pass_rate = (
        100.0 * totals["rows_passed"] / totals["rows_seen"]
        if totals["rows_seen"] > 0
        else 0.0
    )
    last_shard = shard_records[-1]["filename"] if shard_records else "(none)"
    content = f"""# Filtered Institutional Books

Built from [`{SOURCE_DATASET}`](https://huggingface.co/datasets/{SOURCE_DATASET}).

**Redistribution note:** The source dataset's terms prohibit public mirrors. This
repo is intended to be **private** and is shared only with users who themselves
have been granted access to the source dataset.

## Filters

| Field | Rule |
|---|---|
| `language_gen` | `== "eng"` |
| `date1_src`    | parsed year `< {args.year_max}` |
| `ocr_score_src`| `> {args.ocr_min}` |
| `ocr_score_gen`| `> {args.ocr_min}` |
| OCR agreement  | `|src - gen| < {args.ocr_disagreement_max}` |

## Stats

- Source rows seen: **{totals['rows_seen']:,}**
- Rows passed filter: **{totals['rows_passed']:,}** ({pass_rate:.2f}% pass rate)
- Total characters written: **{totals['total_chars']:,}**
- Total shards: **{totals['num_shards']:,}**
- Train shards: `shard_00000.parquet` ... `shard_{max(0, totals['num_shards']-2):05d}.parquet`
- Val shard: `{last_shard}` (last lexicographic shard, per nanochat convention)

### Rejections by reason
{rejection_lines if rejection_lines else "  (none)"}

## Schema

Single string column named `text`. ZSTD-3 compressed, row-group size {args.row_group_size}.
Drop-in compatible with `nanochat/dataset.py` (which reads only the `text` column
and treats the last lexicographic shard as the validation split).

## Use with nanochat

Two ways to load this:

**Option A — minimal-edit path (recommended):**
Rename the local directory to `base_data_climbmix/` so it matches
`DATA_DIR` in `nanochat/dataset.py:27`. Existing scripts auto-discover it.

**Option B — code edit:**
Edit `nanochat/dataset.py:27` to point `DATA_DIR` at
`base_data_books` (or whatever name you used).

Either way, re-train the tokenizer first since this corpus differs from ClimbMix:

```bash
python -m scripts.tok_train
python -m scripts.tok_eval
python -m scripts.base_train --depth=12 --window-pattern=L
```

## Reproducibility

Regenerated by `dev/repackage_institutional_books.py` with:

```bash
python dev/repackage_institutional_books.py \\
    --year-max {args.year_max} \\
    --ocr-min {args.ocr_min} \\
    --ocr-disagreement-max {args.ocr_disagreement_max} \\
    --chars-per-shard {args.chars_per_shard} \\
    --row-group-size {args.row_group_size}
```
"""
    tmp = os.path.join(output_dir, README_FILENAME + ".tmp")
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, os.path.join(output_dir, README_FILENAME))


# -----------------------------------------------------------------------------
# HF upload

def upload_to_hf(output_dir, repo_id, token):
    if not token:
        raise SystemExit("HF_TOKEN missing. Add it to .env at the repo root.")
    api = HfApi(token=token)
    print(f"Ensuring repo exists (private=True): {repo_id}")
    api.create_repo(repo_id=repo_id, repo_type="dataset", private=True, exist_ok=True)
    print(f"Uploading {output_dir} -> {repo_id}")
    api.upload_large_folder(
        folder_path=output_dir,
        repo_id=repo_id,
        repo_type="dataset",
        ignore_patterns=[".state.json", "*.tmp"],
    )
    print(f"Upload complete: https://huggingface.co/datasets/{repo_id}")


# -----------------------------------------------------------------------------
# Main processing loop

def verify_schema(row, text_column):
    """Print discovered schema; assert required columns exist. Returns nothing."""
    keys = list(row.keys())
    print(f"Source row keys ({len(keys)}): {keys}")
    print(f"Sample values:")
    for k in keys[:20]:
        v = row[k]
        sv = (v[:80] + "...") if isinstance(v, str) and len(v) > 80 else v
        print(f"  {k}: {sv!r}")
    missing = [c for c in (text_column,) + REQUIRED_COLUMNS if c not in row]
    if missing:
        raise SystemExit(
            f"\nFATAL: source row is missing required columns: {missing}\n"
            f"Available columns: {keys}\n"
            f"If the text column has a different name, re-run with "
            f"--text-column <name>."
        )


def process(args, token):
    os.makedirs(args.output_dir, exist_ok=True)

    state = load_state(args.output_dir)
    if state is not None:
        print(f"Resuming from state: {state}")
    else:
        state = {
            "shard_index": 0,
            "rows_seen": 0,
            "rows_passed": 0,
            "total_chars": 0,
            "rejections": {},
            "shards": [],  # list of {index, filename, num_docs, num_chars}
            "last_updated": None,
        }

    print(f"Loading streaming dataset: {SOURCE_DATASET} (split={SOURCE_SPLIT})")
    ds = load_dataset(SOURCE_DATASET, split=SOURCE_SPLIT, streaming=True, token=token)

    if state["rows_seen"] > 0:
        print(f"Skipping first {state['rows_seen']:,} rows to resume...")
        ds = ds.skip(state["rows_seen"])

    # Per-run counters (rows processed since this invocation started)
    schema_verified = False
    shard_index = state["shard_index"]
    shard_docs = []
    shard_chars = 0
    run_rows_seen = 0
    t_start = time.time()
    t_last_log = t_start

    # graceful shutdown: just exit; state is already on disk from last shard flush
    def _sigterm(signum, frame):
        print(f"\nReceived signal {signum}; exiting. Current state is on disk "
              f"(progress within in-flight shard {shard_index} will be re-processed on resume).")
        sys.exit(0)
    signal.signal(signal.SIGTERM, _sigterm)

    try:
        for row in ds:
            run_rows_seen += 1

            if not schema_verified:
                verify_schema(row, args.text_column)
                schema_verified = True

            verdict, reason = classify_row(
                row, args.year_max, args.ocr_min, args.ocr_disagreement_max
            )
            if verdict == "reject":
                state["rejections"][reason] = state["rejections"].get(reason, 0) + 1
            else:
                text = row.get(args.text_column)
                if isinstance(text, str) and text:
                    shard_docs.append(text)
                    shard_chars += len(text)
                    state["rows_passed"] += 1
                else:
                    state["rejections"]["empty_text"] = state["rejections"].get("empty_text", 0) + 1

            # NOTE: state['rows_seen'] is only persisted on shard flush, but we
            # track a running total locally for logging.
            running_rows_seen = state["rows_seen"] + run_rows_seen

            # Periodic log
            now = time.time()
            if now - t_last_log > 15.0:
                rate = run_rows_seen / max(1e-6, now - t_start)
                pass_rate = 100.0 * state["rows_passed"] / max(1, running_rows_seen)
                print(
                    f"[{now - t_start:6.0f}s] rows_seen={running_rows_seen:,} "
                    f"passed={state['rows_passed']:,} ({pass_rate:.2f}%) "
                    f"shard={shard_index} buf_docs={len(shard_docs)} "
                    f"buf_chars={shard_chars:,} ({100.0*shard_chars/args.chars_per_shard:.1f}% full) "
                    f"rate={rate:.1f} rows/s"
                )
                t_last_log = now

            # Flush shard when char budget hit
            if shard_chars >= args.chars_per_shard:
                filename, _ = write_shard(
                    args.output_dir, shard_index, shard_docs, args.row_group_size
                )
                shard_record = {
                    "index": shard_index,
                    "filename": filename,
                    "num_docs": len(shard_docs),
                    "num_chars": shard_chars,
                }
                state["shards"].append(shard_record)
                state["total_chars"] += shard_chars
                state["rows_seen"] = running_rows_seen
                state["shard_index"] = shard_index + 1
                state["last_updated"] = datetime.now(timezone.utc).isoformat()
                save_state_atomic(args.output_dir, state)
                print(
                    f"WROTE {filename} | docs={len(shard_docs):,} chars={shard_chars:,} "
                    f"(total shards={shard_index + 1}, total chars={state['total_chars']:,})"
                )
                shard_index += 1
                shard_docs = []
                shard_chars = 0
                run_rows_seen = 0  # reset; state['rows_seen'] now captures pre-flush count
                t_start = time.time()
                t_last_log = t_start

                if args.max_shards > 0 and shard_index >= args.max_shards:
                    print(f"Reached --max-shards={args.max_shards}, stopping.")
                    break

            if args.max_rows > 0 and running_rows_seen >= args.max_rows:
                print(f"Reached --max-rows={args.max_rows}, stopping.")
                break

    except KeyboardInterrupt:
        print(f"\nKeyboardInterrupt: exiting. In-flight shard {shard_index} buffer "
              f"({len(shard_docs)} docs, {shard_chars:,} chars) discarded; will be "
              f"re-processed on resume.")
        # don't write the partial shard; state already reflects last flush

    # End of stream — flush whatever's left as a final shard
    if shard_docs:
        filename, _ = write_shard(
            args.output_dir, shard_index, shard_docs, args.row_group_size
        )
        state["shards"].append({
            "index": shard_index,
            "filename": filename,
            "num_docs": len(shard_docs),
            "num_chars": shard_chars,
        })
        state["total_chars"] += shard_chars
        state["rows_seen"] = state["rows_seen"] + run_rows_seen
        state["shard_index"] = shard_index + 1
        state["last_updated"] = datetime.now(timezone.utc).isoformat()
        save_state_atomic(args.output_dir, state)
        print(f"WROTE final shard {filename} | docs={len(shard_docs):,} chars={shard_chars:,}")

    # Write README + manifest summarising the run
    totals = {
        "rows_seen": state["rows_seen"],
        "rows_passed": state["rows_passed"],
        "total_chars": state["total_chars"],
        "num_shards": len(state["shards"]),
        "rejections": state["rejections"],
    }
    update_manifest(args.output_dir, args, state["shards"], totals)
    write_readme(args.output_dir, args, totals, state["shards"])
    print("\n=== Done ===")
    print(f"Output dir: {args.output_dir}")
    print(f"Total shards: {totals['num_shards']}")
    print(f"Total chars:  {totals['total_chars']:,}")
    print(f"Rows passed:  {totals['rows_passed']:,} / {totals['rows_seen']:,}")
    print(f"Rejections:   {totals['rejections']}")


# -----------------------------------------------------------------------------
# CLI

def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--output-dir", type=str, required=True,
                   help="Directory to write shards to (e.g. $NANOCHAT_BASE_DIR/base_data_books)")
    p.add_argument("--year-max", type=int, default=1930,
                   help="Exclusive upper bound on parsed year (default: 1930)")
    p.add_argument("--ocr-min", type=float, default=85.0,
                   help="Exclusive lower bound on each OCR score (default: 85)")
    p.add_argument("--ocr-disagreement-max", type=float, default=15.0,
                   help="Exclusive upper bound on |src - gen| OCR disagreement (default: 15)")
    p.add_argument("--text-column", type=str, default="text",
                   help="Name of the source column containing book text (default: text)")
    p.add_argument("--chars-per-shard", type=int, default=250_000_000,
                   help="Target characters per shard before flush (default: 250M, matches ClimbMix's "
                        "~100MB-compressed target with ZSTD-3)")
    p.add_argument("--row-group-size", type=int, default=64,
                   help="Parquet row group size (default: 64, smaller than ClimbMix's 1024 because "
                        "institutional-books rows average ~1M chars/book vs ClimbMix's ~250K-char web docs. "
                        "At ~250 books/shard, row_group_size=64 yields ~4 row groups per shard — DDP-friendly "
                        "up to 4-way and keeps peak per-load memory bounded even for multi-volume 10M-char books)")
    p.add_argument("--max-shards", type=int, default=-1,
                   help="Stop after writing this many shards (-1 = unlimited)")
    p.add_argument("--max-rows", type=int, default=-1,
                   help="Stop after seeing this many source rows (-1 = unlimited)")
    p.add_argument("--upload", action="store_true",
                   help="Upload to HF after processing completes")
    p.add_argument("--upload-only", action="store_true",
                   help="Skip processing; only upload an already-built output dir")
    p.add_argument("--repo-id", type=str, default="jbduran/think-institutional-books",
                   help="HF dataset repo id (will be created private if missing)")
    return p.parse_args()


def main():
    args = parse_args()

    # Load HF_TOKEN from .env at repo root (or wherever find_dotenv locates it)
    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path)
        print(f"Loaded .env from {dotenv_path}")
    else:
        print("Warning: no .env found; relying on environment HF_TOKEN")
    token = os.getenv("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN not set. Put it in .env at the repo root.")

    if args.upload_only:
        upload_to_hf(args.output_dir, args.repo_id, token)
        return

    process(args, token)

    if args.upload:
        upload_to_hf(args.output_dir, args.repo_id, token)


if __name__ == "__main__":
    main()
