"""
Stream, filter, dedup, shuffle, and repackage `institutional/institutional-books-1.0`
into nanochat-compatible parquet shards.

Filters applied (all must pass; first match wins):
  - language_gen == "eng"
  - parsed year of date1_src (fallback date2_src) < --year-max (default 1930)
    rows where neither date parses are REJECTED (no leakage path for modern data)
  - ocr_score_src  > --ocr-min (default 85)
  - ocr_score_gen  > --ocr-min (default 85)
  - |ocr_score_src - ocr_score_gen| < --ocr-disagreement-max (default 15)

Dedup (on by default; disable with --no-dedup):
  Uses `likely_duplicates_barcodes_gen`. When a book is kept, its barcode and all
  barcodes in its duplicates list are "claimed"; a later book whose barcode is
  already claimed is dropped (first-seen representative kept). The claimed set is
  IN-MEMORY ONLY and is rebuilt from scratch on each (re)stream — never persisted
  (persisting it would make a resume re-stream drop the first occurrence of every
  kept book as a "duplicate").

Diversity — single streaming pass through a large in-memory shuffle buffer:
  Training books accumulate in a buffer holding UTF-8 *bytes* (not str: CPython
  widens a whole string to 2-4 bytes/char on any non-Latin char, so a str buffer
  could 2-4x memory and OOM; bytes is a predictable ~1 byte/char for English).
  When the buffer exceeds --shuffle-buffer-gb, a uniformly random entry is evicted
  to the current output shard. Uniform eviction preserves the corpus's natural
  topic distribution while decorrelating order. The buffer must be >= the longest
  pure source cluster (LAW arrives in ~10-20K consecutive-book runs) to fully break
  it; 20 GB ~= 20K books covers it on a 51 GB box.

Validation split — deterministic by barcode hash (resume-stable):
  A book is val iff zlib.crc32(barcode) % val_divisor == 0, where
  val_divisor = max(1, round(EST_PASSING / --val-target)). No count cap (a cap is
  arrival-order-dependent and not resume-stable). Val books are held in memory
  (~1 GB at --val-target 1000) and written as the LAST lexicographic shard so
  nanochat's last-file-is-val convention picks them up.

Bandwidth: only the columns actually needed are streamed via select_columns,
skipping the redundant `text_by_page_src` (a second full copy of every book's raw
OCR text) and the analysis columns — roughly halving download.

Resume (durable across Colab session resets):
  Completed shards are durable (and, with --upload-incremental, on HF). Each
  successfully-written shard's barcodes are recorded in `committed_written` INSIDE
  .state.json (one atomic write per flush). On resume the script RE-STREAMS FROM
  ROW 0 and skips any barcode already in committed_written — correct (no loss, no
  duplicates) without checkpointing the in-memory buffer. Cost: re-downloads the
  consumed prefix (HF streaming skip re-downloads anyway). val_divisor is fixed so
  the val membership is identical across runs.

Output layout (drop-in compatible with nanochat/dataset.py):
  <output_dir>/
    shard_00000.parquet         # train
    ...
    shard_NNNNN.parquet         # val (last lexicographic shard)
    .state.json                 # resume checkpoint (incl. committed_written)
    README.md                   # provenance + stats + topic breakdown
    manifest.json               # per-shard breakdown (incl. topic_distribution)

Each shard parquet: single `text` string column, ZSTD-3, row_group_size=64,
chars_per_shard=250M, use_dictionary=False, write_statistics=False.

Schema (verified live via HF dataset_info):
  - text_by_page_gen: sequence(large_string)  <- joined with "\\n\\n" per book
  - language_gen, date1_src, date2_src, topic_or_subject_gen: string
  - ocr_score_src, ocr_score_gen: int32
  - barcode_src: string (primary key); likely_duplicates_barcodes_gen: sequence(string)

Usage:
    # Process to local SSD, keep shards
    python dev/repackage_institutional_books.py --output-dir /content/base_data_books

    # Process + incrementally upload each shard to HF, freeing local disk
    python dev/repackage_institutional_books.py --output-dir /content/base_data_books \
        --upload-incremental --repo-id jbduran/think-institutional-books

    # Upload an already-built dir in one shot
    python dev/repackage_institutional_books.py --output-dir /content/base_data_books \
        --upload-only --repo-id jbduran/think-institutional-books

Requires HF_TOKEN in .env (project root) with access to the gated dataset.
"""

import argparse
import json
import os
import random
import re
import signal
import sys
import time
import zlib
from collections import Counter
from datetime import datetime, timezone

import huggingface_hub
import pyarrow as pa
import pyarrow.parquet as pq
from datasets import load_dataset
from dotenv import find_dotenv, load_dotenv
from huggingface_hub import HfApi


SOURCE_DATASET = "institutional/institutional-books-1.0"
SOURCE_SPLIT = "train"
REQUIRED_FILTER_COLUMNS = (
    "language_gen", "date1_src", "date2_src", "ocr_score_src", "ocr_score_gen",
)
DEDUP_COLUMNS = ("barcode_src", "likely_duplicates_barcodes_gen")
STATE_FILENAME = ".state.json"
README_FILENAME = "README.md"
MANIFEST_FILENAME = "manifest.json"
UNKNOWN_TOPIC = "UNKNOWN"
# Report's ~360-380K English+pre-1930+OCR passing estimate; used only to derive
# the val hash divisor so --val-target yields roughly that many val books.
EST_PASSING = 370_000


# -----------------------------------------------------------------------------
# Filtering

_YEAR_RE = re.compile(r"\d{4}")


def parse_year(date_str):
    """Extract a plausible 4-digit year from a MARC date string.

    Returns int year in [1000, 2100], or None. MARC date fields contain
    artifacts like '18uu', '9999', '0000', '    '.
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


def resolve_year(row):
    """Try date1_src, then date2_src. Returns (year_or_None, source_field_or_None)."""
    for field in ("date1_src", "date2_src"):
        y = parse_year(row.get(field))
        if y is not None:
            return y, field
    return None, None


def classify_row(row, year_max, ocr_min, ocr_disagreement_max):
    """Return ('pass', year_src_field) or ('reject', reason_str)."""
    if row.get("language_gen") != "eng":
        return "reject", "language"

    year, year_src = resolve_year(row)
    if year is None:
        return "reject", "year_unparseable"  # no leakage path for undated rows
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

    return "pass", year_src


def extract_text(row, col_name):
    """Extract the book's text. text_by_page_gen is a list of page strings,
    joined with double newline. Falls back to single-string columns."""
    val = row.get(col_name)
    if val is None:
        return None
    if isinstance(val, list):
        return "\n\n".join(str(p) for p in val if p)
    if isinstance(val, str):
        return val
    return None


def is_duplicate(row, seen_barcodes):
    bc = row.get("barcode_src")
    return bc is not None and bc in seen_barcodes


def claim_barcodes(row, seen_barcodes):
    """Claim this book's barcode and all its likely-duplicate barcodes."""
    bc = row.get("barcode_src")
    if bc is not None:
        seen_barcodes.add(bc)
    dups = row.get("likely_duplicates_barcodes_gen")
    if dups:
        for d in dups:
            if d:
                seen_barcodes.add(d)


def is_val(barcode, val_divisor):
    """Deterministic, resume-stable val membership by barcode hash."""
    return zlib.crc32(barcode.encode("utf-8")) % val_divisor == 0


# -----------------------------------------------------------------------------
# State persistence (resume). committed_written lives INSIDE state for atomicity.

def _atomic_write(path, write_fn):
    tmp = path + ".tmp"
    write_fn(tmp)
    os.replace(tmp, path)


def state_path(output_dir):
    return os.path.join(output_dir, STATE_FILENAME)


def load_state(output_dir):
    p = state_path(output_dir)
    if not os.path.exists(p):
        return None
    with open(p, "r") as f:
        return json.load(f)


def save_state_atomic(output_dir, state):
    def _w(tmp):
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
    _atomic_write(state_path(output_dir), _w)


# -----------------------------------------------------------------------------
# Shard writing + optional incremental upload

def write_shard(output_dir, shard_index, docs, row_group_size):
    """Write a single shard. Atomic via .tmp + rename. Single `text` column only."""
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
    return filename, final_path


def _with_upload_retry(fn, *, what, max_attempts=6):
    """Call an HF upload fn with exponential backoff on rate-limit/network errors.

    Handles HTTP 429 (commit rate limit) and transient connection drops by
    sleeping the server-suggested time (or exponential backoff) and retrying.
    """
    import time as _time
    from huggingface_hub.errors import HfHubHTTPError
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except HfHubHTTPError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            retriable = status in (429, 500, 502, 503, 504)
            if not retriable or attempt == max_attempts:
                raise
            wait = None
            resp = getattr(e, "response", None)
            if resp is not None:
                ra = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
                if ra:
                    try:
                        wait = int(ra)
                    except ValueError:
                        wait = None
            if wait is None:
                wait = min(300, 20 * (2 ** (attempt - 1)))
            print(f"  upload {what}: {status} (attempt {attempt}/{max_attempts}); "
                  f"retrying in {wait}s...")
            _time.sleep(wait)
        except Exception as e:  # transient connection errors (httpx/httpcore)
            if attempt == max_attempts:
                raise
            wait = min(120, 15 * (2 ** (attempt - 1)))
            print(f"  upload {what}: {type(e).__name__} (attempt {attempt}/{max_attempts}); "
                  f"retrying in {wait}s...")
            _time.sleep(wait)


def upload_batch_and_delete(api, repo_id, output_dir, filenames):
    """Upload a batch of shard files in ONE commit, then delete them locally.

    Batching is the key fix for HF's 128-commits/hour cap: one commit per
    batch instead of one per shard. `upload_folder` with allow_patterns puts
    all listed files into a single commit.
    """
    if not filenames:
        return
    _with_upload_retry(
        lambda: api.upload_folder(
            folder_path=output_dir,
            repo_id=repo_id,
            repo_type="dataset",
            allow_patterns=list(filenames),
            commit_message=f"Add {len(filenames)} shard(s): {filenames[0]}..{filenames[-1]}",
        ),
        what=f"batch[{filenames[0]}..{filenames[-1]}]",
    )
    for fn in filenames:
        p = os.path.join(output_dir, fn)
        if os.path.exists(p):
            os.remove(p)


# -----------------------------------------------------------------------------
# Manifest + README

def update_manifest(output_dir, args, shard_records, totals, val_divisor):
    manifest = {
        "source_dataset": SOURCE_DATASET,
        "source_split": SOURCE_SPLIT,
        "filters": {
            "language": "eng",
            "year_max_exclusive": args.year_max,
            "ocr_min_exclusive": args.ocr_min,
            "ocr_disagreement_max_exclusive": args.ocr_disagreement_max,
            "undated_rows_rejected": True,
        },
        "dedup": {
            "enabled": not args.no_dedup,
            "method": "likely_duplicates_barcodes_gen barcode claiming",
        },
        "diversity": {
            "method": "single shuffle buffer + uniform random eviction",
            "shuffle_buffer_gb": args.shuffle_buffer_gb,
            "val_target": args.val_target,
            "val_divisor": val_divisor,
            "shuffle_seed": args.shuffle_seed,
            "topic_column": args.topic_column,
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
    def _w(tmp):
        with open(tmp, "w") as f:
            json.dump(manifest, f, indent=2)
    _atomic_write(os.path.join(output_dir, MANIFEST_FILENAME), _w)


def _format_topic_table(topic_counts):
    if not topic_counts:
        return "  (no topic data)"
    total = sum(topic_counts.values())
    return "\n".join(
        f"  - `{t}`: {c:,} ({100.0 * c / total:.2f}%)"
        for t, c in sorted(topic_counts.items(), key=lambda x: -x[1])
    )


def write_readme(output_dir, args, totals, shard_records, val_divisor):
    rejection_lines = "\n".join(
        f"  - `{k}`: {v:,}" for k, v in sorted(totals["rejections"].items())
    )
    pass_rate = (
        100.0 * totals["rows_passed"] / totals["rows_seen"]
        if totals["rows_seen"] > 0 else 0.0
    )
    last_shard = shard_records[-1]["filename"] if shard_records else "(none)"
    train_count = max(0, totals["num_shards"] - 1)
    year_src_lines = "\n".join(
        f"  - `{k}`: {v:,}" for k, v in sorted(totals.get("pass_by_year_source", {}).items())
    ) or "  (none)"
    topic_table = _format_topic_table(totals.get("topic_distribution_overall", {}))
    content = f"""# Filtered Institutional Books

Built from [`{SOURCE_DATASET}`](https://huggingface.co/datasets/{SOURCE_DATASET}).

**Redistribution note:** The source dataset's terms prohibit public mirrors. This
repo is intended to be **private** and shared only with users who themselves have
been granted access to the source dataset.

## Filters

| Field | Rule |
|---|---|
| `language_gen` | `== "eng"` |
| `date1_src` → `date2_src` fallback | parsed year `< {args.year_max}` (undated REJECTED) |
| `ocr_score_src`| `> {args.ocr_min}` |
| `ocr_score_gen`| `> {args.ocr_min}` |
| OCR agreement  | `\\|src - gen\\| < {args.ocr_disagreement_max}` |

## Dedup

{"Enabled" if not args.no_dedup else "DISABLED (--no-dedup)"} — via `likely_duplicates_barcodes_gen` barcode claiming (first-seen representative kept).

## Diversity strategy

- **Single shuffle buffer**: training books accumulate in a UTF-8-bytes buffer; when it exceeds **{args.shuffle_buffer_gb} GB** a uniformly random book is evicted to the current output shard. Decorrelates the source's library-archive clustering while preserving the corpus's natural topic distribution. Buffer must be ≥ the longest pure cluster to fully break it.
- **Validation split**: deterministic by barcode hash — a book is val iff `crc32(barcode) % {val_divisor} == 0` (~`{args.val_target}` books). Resume-stable; written as the last lexicographic shard.

## Stats

- Source rows seen: **{totals['rows_seen']:,}**
- Rows passed filter + dedup: **{totals['rows_passed']:,}** ({pass_rate:.2f}% of seen)
- Total characters written: **{totals['total_chars']:,}**
- Total shards: **{totals['num_shards']:,}**  (train: {train_count}, val: 1)
- Last shard (val): `{last_shard}`

### Rejections by reason
{rejection_lines if rejection_lines else "  (none)"}

### Pass-by-year-source (date1_src vs date2_src fallback recovery)
{year_src_lines}

### Overall topic distribution
{topic_table}

## Schema

Single string column named `text`. ZSTD-3, row-group size {args.row_group_size}.
Drop-in compatible with `nanochat/dataset.py`. Per-shard topic distribution lives
in `manifest.json` (`shards[].topic_distribution`).

## Use with nanochat

Rename to `base_data_climbmix/` (matches `DATA_DIR` in `nanochat/dataset.py:27`)
or edit that constant to point at this directory. Then re-train the tokenizer:

```bash
python -m scripts.tok_train && python -m scripts.tok_eval
python -m scripts.base_train --depth=12 --window-pattern=L
```
"""
    def _w(tmp):
        with open(tmp, "w") as f:
            f.write(content)
    _atomic_write(os.path.join(output_dir, README_FILENAME), _w)


# -----------------------------------------------------------------------------
# HF upload (one-shot)

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
# Schema verification

def verify_schema(row, text_column, topic_column, dedup_enabled):
    """Print discovered schema; assert required columns; return whether topic col exists."""
    keys = list(row.keys())
    print(f"\nSource row keys ({len(keys)}): {keys}")
    print("Sample values:")
    for k in keys[:25]:
        v = row[k]
        if isinstance(v, str):
            print(f"  {k}: {(v[:80] + '...') if len(v) > 80 else v!r}")
        elif isinstance(v, list):
            preview = ""
            if v:
                first = str(v[0])
                preview = f" first={(first[:60] + '...') if len(first) > 60 else first!r}"
            print(f"  {k}: [list len={len(v)}]{preview}")
        else:
            print(f"  {k}: {v!r}"[:120])

    missing = [c for c in (text_column,) + REQUIRED_FILTER_COLUMNS if c not in row]
    if missing:
        raise SystemExit(
            f"\nFATAL: source row missing required columns: {missing}\n"
            f"Available: {keys}\nRe-run with --text-column NAME if needed."
        )

    if dedup_enabled:
        missing_dedup = [c for c in DEDUP_COLUMNS if c not in row]
        if missing_dedup:
            print(f"\nWARNING: dedup columns missing {missing_dedup}; dedup will be a no-op.")

    has_topic = topic_column in row
    if not has_topic:
        print(f"\nWARNING: topic column '{topic_column}' not present; "
              f"per-shard topic stats will be UNKNOWN.")
    sample_text = row.get(text_column)
    if isinstance(sample_text, list):
        print(f"\nText column '{text_column}' is list-of-pages; joined with '\\n\\n'.")
    print()
    return has_topic


# -----------------------------------------------------------------------------
# Main processing loop

def process(args, token):
    os.makedirs(args.output_dir, exist_ok=True)

    val_divisor = max(1, round(EST_PASSING / args.val_target))
    buf_limit = int(args.shuffle_buffer_gb * (1024 ** 3))
    print(f"val_divisor={val_divisor} (target ~{args.val_target} val books), "
          f"shuffle buffer limit={args.shuffle_buffer_gb} GB ({buf_limit:,} bytes)")

    # Incremental-upload setup
    api = None
    if args.upload_incremental:
        api = HfApi(token=token)
        print(f"Incremental upload enabled -> {args.repo_id} (created private if missing)")
        api.create_repo(repo_id=args.repo_id, repo_type="dataset", private=True, exist_ok=True)

    state = load_state(args.output_dir)
    if state is None:
        state = {
            "shard_index": 0, "rows_seen": 0, "rows_passed": 0, "total_chars": 0,
            "rejections": {}, "pass_by_year_source": {},
            "topic_distribution_overall": {}, "shards": [],
            "committed_written": [], "last_updated": None,
        }
    else:
        print(f"Resuming: shard_index={state['shard_index']}, "
              f"rows_passed={state['rows_passed']:,}, "
              f"committed={len(state.get('committed_written', [])):,}")
        state.setdefault("pass_by_year_source", {})
        state.setdefault("topic_distribution_overall", {})
        state.setdefault("committed_written", [])

    committed = set(state["committed_written"])

    # Startup recovery (incremental upload): reconcile local shard files with state.
    # - index < state.shard_index  -> accounted-for in state but maybe not yet on HF
    #   (e.g. crash mid-batch); upload them in one batch, then delete.
    # - index >= state.shard_index -> orphan from a crash before the write was
    #   recorded in state; delete so it gets cleanly regenerated (no duplicate).
    if api is not None:
        import glob as _glob, re as _re
        recover, orphans = [], []
        for p in sorted(_glob.glob(os.path.join(args.output_dir, "shard_*.parquet"))):
            m = _re.search(r"shard_(\d+)\.parquet$", p)
            if not m:
                continue
            idx = int(m.group(1))
            (recover if idx < state["shard_index"] else orphans).append((idx, os.path.basename(p)))
        for _, fn in orphans:
            op = os.path.join(args.output_dir, fn)
            if os.path.exists(op):
                os.remove(op)
                print(f"Removed orphan local shard {fn} (>= shard_index, will regenerate)")
        if recover:
            recover.sort()
            names = [fn for _, fn in recover]
            print(f"Recovering {len(names)} un-uploaded local shard(s) -> HF in one batch...")
            upload_batch_and_delete(api, args.repo_id, args.output_dir, names)

    print("Authenticating to HuggingFace (gated dataset)...")
    huggingface_hub.login(token=token, add_to_git_credential=False)

    # Make streaming reads resilient to transient HF connection drops
    # (RemoteProtocolError: "peer closed connection without sending complete body").
    try:
        import datasets as _datasets
        _datasets.config.STREAMING_READ_MAX_RETRIES = max(
            getattr(_datasets.config, "STREAMING_READ_MAX_RETRIES", 0), 20)
        _datasets.config.STREAMING_READ_RETRY_INTERVAL = max(
            getattr(_datasets.config, "STREAMING_READ_RETRY_INTERVAL", 0), 5)
    except Exception as e:
        print(f"(could not raise streaming retry config: {e})")

    print(f"Loading streaming dataset: {SOURCE_DATASET} (split={SOURCE_SPLIT})")
    ds = load_dataset(SOURCE_DATASET, split=SOURCE_SPLIT, streaming=True)

    # Column projection — only stream what we use (skips redundant text_by_page_src etc.)
    needed = {args.text_column, "language_gen", "date1_src", "date2_src",
              "ocr_score_src", "ocr_score_gen", args.topic_column}
    if not args.no_dedup:
        needed.update(DEDUP_COLUMNS)
    needed.add("barcode_src")  # always required for val/resume keys
    try:
        ds = ds.select_columns(sorted(needed))
        print(f"Streaming only {len(needed)} columns: {sorted(needed)}")
    except Exception as e:
        print(f"select_columns failed ({e}); streaming all columns (slower).")

    # NOTE: NO ds.skip on resume. The shuffle buffer holds books from arbitrary
    # source positions, so a row-counter skip would drop buffered-but-unwritten
    # books. We re-stream from row 0 and rely on `committed` to skip already-written.

    # In-flight state
    schema_verified = False
    has_topic_column = True
    shard_index = state["shard_index"]
    shard_docs, shard_topics, shard_barcodes = [], [], []
    shard_chars = 0
    buffer = []        # list of (text_bytes, topic, barcode)
    buf_bytes = 0
    val_buffer = []    # list of (text_bytes, topic, barcode), held to end
    seen_barcodes = set()  # in-memory dedup set, rebuilt this stream (never persisted)
    run_rows_seen = 0
    rng = random.Random(args.shuffle_seed)
    t_start = time.time()
    t_last_log = t_start
    pending_uploads = []  # shard filenames written locally but not yet uploaded (batched)

    def add_to_shard(text, topic, barcode):
        nonlocal shard_chars
        shard_docs.append(text)
        shard_topics.append(topic)
        shard_barcodes.append(barcode)
        shard_chars += len(text)

    def flush_uploads():
        """Upload all pending shards to HF in ONE commit, then delete locally."""
        if api is None or not pending_uploads:
            return
        upload_batch_and_delete(api, args.repo_id, args.output_dir, list(pending_uploads))
        print(f"  uploaded batch of {len(pending_uploads)} shard(s) in 1 commit "
              f"(rate-limit safe)")
        pending_uploads.clear()

    def flush_shard():
        nonlocal shard_index, shard_chars
        if not shard_docs:
            return
        # 1) shard durable on disk
        filename, _ = write_shard(
            args.output_dir, shard_index, shard_docs, args.row_group_size
        )
        # 2) record state + committed barcodes (atomic). committed and the shard
        #    live on the same disk, so they can never disagree on resume.
        topic_counts = dict(Counter(shard_topics))
        state["shards"].append({
            "index": shard_index, "filename": filename,
            "num_docs": len(shard_docs), "num_chars": shard_chars,
            "topic_distribution": topic_counts,
        })
        state["total_chars"] += shard_chars
        state["shard_index"] = shard_index + 1
        state["last_updated"] = datetime.now(timezone.utc).isoformat()
        for t, c in topic_counts.items():
            state["topic_distribution_overall"][t] = state["topic_distribution_overall"].get(t, 0) + c
        committed.update(shard_barcodes)
        state["committed_written"] = sorted(committed)
        save_state_atomic(args.output_dir, state)
        top3 = sorted(topic_counts.items(), key=lambda x: -x[1])[:3]
        print(f"WROTE {filename} | docs={len(shard_docs):,} chars={shard_chars:,} top3={top3}")
        # 3) queue for batched upload (one commit per --upload-batch shards)
        if api is not None:
            pending_uploads.append(filename)
            if len(pending_uploads) >= args.upload_batch:
                flush_uploads()
        shard_index += 1
        shard_docs.clear()
        shard_topics.clear()
        shard_barcodes.clear()
        shard_chars = 0

    def maybe_flush():
        if shard_chars >= args.chars_per_shard:
            flush_shard()

    def evict_one():
        """Evict a uniformly random book from the buffer into the current shard."""
        nonlocal buf_bytes
        i = rng.randrange(len(buffer))
        buffer[i], buffer[-1] = buffer[-1], buffer[i]  # O(1) swap-and-pop
        tb, topic, bc = buffer.pop()
        buf_bytes -= len(tb)
        add_to_shard(tb.decode("utf-8"), topic, bc)
        maybe_flush()

    def _sigterm(signum, frame):
        print(f"\nSignal {signum}; exiting cleanly. State on disk; in-flight buffer discarded "
              f"(re-streamed + skipped via committed on resume).")
        sys.exit(0)
    signal.signal(signal.SIGTERM, _sigterm)

    try:
        for row in ds:
            run_rows_seen += 1

            if not schema_verified:
                has_topic_column = verify_schema(
                    row, args.text_column, args.topic_column, not args.no_dedup
                )
                schema_verified = True

            verdict, year_or_reason = classify_row(
                row, args.year_max, args.ocr_min, args.ocr_disagreement_max
            )
            if verdict == "reject":
                state["rejections"][year_or_reason] = state["rejections"].get(year_or_reason, 0) + 1
            else:
                year_src = year_or_reason
                text = extract_text(row, args.text_column)
                if not text:
                    state["rejections"]["empty_text"] = state["rejections"].get("empty_text", 0) + 1
                else:
                    bc = row.get("barcode_src")
                    if not bc:
                        # No stable key => cannot dedup, val-hash, or resume-skip it.
                        state["rejections"]["no_barcode"] = state["rejections"].get("no_barcode", 0) + 1
                    elif (not args.no_dedup) and is_duplicate(row, seen_barcodes):
                        state["rejections"]["duplicate"] = state["rejections"].get("duplicate", 0) + 1
                    else:
                        # Claim BEFORE the committed-skip so a kept book's duplicates
                        # stay suppressed even when the representative was written last run.
                        if not args.no_dedup:
                            claim_barcodes(row, seen_barcodes)
                        if bc in committed:
                            pass  # already written in a prior run (resume skip)
                        else:
                            topic = (row.get(args.topic_column) if has_topic_column else None) or UNKNOWN_TOPIC
                            state["pass_by_year_source"][year_src] = state["pass_by_year_source"].get(year_src, 0) + 1
                            state["rows_passed"] += 1
                            tb = text.encode("utf-8")
                            if is_val(bc, val_divisor):
                                val_buffer.append((tb, topic, bc))
                            else:
                                buffer.append((tb, topic, bc))
                                buf_bytes += len(tb)
                                while buf_bytes > buf_limit:
                                    evict_one()
                                    if args.max_shards > 0 and shard_index >= args.max_shards:
                                        break

            now = time.time()
            if now - t_last_log > 15.0:
                running = state["rows_seen"] + run_rows_seen
                rate = run_rows_seen / max(1e-6, now - t_start)
                pr = 100.0 * state["rows_passed"] / max(1, running)
                dups = state["rejections"].get("duplicate", 0)
                print(
                    f"[{now - t_start:6.0f}s] seen={running:,} pass={state['rows_passed']:,} "
                    f"({pr:.2f}%) dups={dups:,} shard={shard_index} "
                    f"buf_docs={len(buffer):,} buf_gb={buf_bytes/1024**3:.2f} "
                    f"val={len(val_buffer):,} shard_chars={shard_chars:,} "
                    f"({100.0*shard_chars/args.chars_per_shard:.1f}%) rate={rate:.1f} rows/s"
                )
                t_last_log = now

            if args.max_shards > 0 and shard_index >= args.max_shards:
                print(f"Reached --max-shards={args.max_shards}, stopping.")
                break
            if args.max_rows > 0 and (state["rows_seen"] + run_rows_seen) >= args.max_rows:
                print(f"Reached --max-rows={args.max_rows}, stopping.")
                break

    except KeyboardInterrupt:
        print(f"\nKeyboardInterrupt: discarding {len(buffer)} buffered docs. "
              f"Resume re-streams + skips committed.")

    # Update rows_seen once at the end (stats only — not used for resume)
    state["rows_seen"] += run_rows_seen

    # Drain the shuffle buffer in random order (only if not stopped by --max-shards)
    if not (args.max_shards > 0 and shard_index >= args.max_shards):
        if buffer:
            print(f"Draining {len(buffer):,} buffered books (random order)...")
        while buffer:
            evict_one()
            if args.max_shards > 0 and shard_index >= args.max_shards:
                break
        if shard_docs:
            flush_shard()

    # Val (hash-selected) -> final (last lexicographic) shard
    if val_buffer and not (args.max_shards > 0 and shard_index >= args.max_shards):
        val_docs = [tb.decode("utf-8") for tb, _, _ in val_buffer]
        val_topics = [top for _, top, _ in val_buffer]
        val_chars = sum(len(d) for d in val_docs)
        filename, _ = write_shard(args.output_dir, state["shard_index"], val_docs, args.row_group_size)
        if api is not None:
            pending_uploads.append(filename)
        topic_counts = dict(Counter(val_topics))
        state["shards"].append({
            "index": state["shard_index"], "filename": filename,
            "num_docs": len(val_docs), "num_chars": val_chars,
            "topic_distribution": topic_counts, "is_val": True,
        })
        state["total_chars"] += val_chars
        state["shard_index"] += 1
        state["last_updated"] = datetime.now(timezone.utc).isoformat()
        for t, c in topic_counts.items():
            state["topic_distribution_overall"][t] = state["topic_distribution_overall"].get(t, 0) + c
        save_state_atomic(args.output_dir, state)
        print(f"WROTE VAL {filename} | docs={len(val_docs):,} chars={val_chars:,}")

    # Flush any remaining queued shards (incl. val) as a final batch commit
    if api is not None and pending_uploads:
        flush_uploads()

    totals = {
        "rows_seen": state["rows_seen"], "rows_passed": state["rows_passed"],
        "total_chars": state["total_chars"], "num_shards": len(state["shards"]),
        "rejections": state["rejections"],
        "pass_by_year_source": state["pass_by_year_source"],
        "topic_distribution_overall": state["topic_distribution_overall"],
    }
    update_manifest(args.output_dir, args, state["shards"], totals, val_divisor)
    write_readme(args.output_dir, args, totals, state["shards"], val_divisor)

    # Push metadata files when incrementally uploading (shards already uploaded)
    if api is not None:
        present = [m for m in (MANIFEST_FILENAME, README_FILENAME)
                   if os.path.exists(os.path.join(args.output_dir, m))]
        if present:
            _with_upload_retry(
                lambda: api.upload_folder(
                    folder_path=args.output_dir, repo_id=args.repo_id,
                    repo_type="dataset", allow_patterns=present,
                    commit_message="Add README + manifest",
                ),
                what="metadata",
            )
        print(f"Uploaded README + manifest to {args.repo_id}")

    print("\n=== Done ===")
    print(f"Output dir:  {args.output_dir}")
    print(f"Shards:      {totals['num_shards']} (incl. 1 val)")
    print(f"Total chars: {totals['total_chars']:,}")
    print(f"Pass rate:   {totals['rows_passed']:,} / {totals['rows_seen']:,} "
          f"({100.0 * totals['rows_passed'] / max(1, totals['rows_seen']):.2f}%)")
    print(f"Rejections:  {totals['rejections']}")
    if totals['pass_by_year_source']:
        print(f"Year source: {totals['pass_by_year_source']}")
    if totals['topic_distribution_overall']:
        top5 = sorted(totals['topic_distribution_overall'].items(), key=lambda x: -x[1])[:5]
        print(f"Top topics:  {top5}")


# -----------------------------------------------------------------------------
# CLI

def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--output-dir", type=str, required=True,
                   help="Directory to write shards to (local SSD recommended, e.g. /content/base_data_books)")
    # Filters
    p.add_argument("--year-max", type=int, default=1930,
                   help="Exclusive upper bound on parsed year (default: 1930)")
    p.add_argument("--ocr-min", type=float, default=85.0,
                   help="Exclusive lower bound on each OCR score (default: 85)")
    p.add_argument("--ocr-disagreement-max", type=float, default=15.0,
                   help="Exclusive upper bound on |src - gen| OCR disagreement (default: 15)")
    # Columns
    p.add_argument("--text-column", type=str, default="text_by_page_gen",
                   help="Source text column (default: text_by_page_gen, joined with '\\n\\n')")
    p.add_argument("--topic-column", type=str, default="topic_or_subject_gen",
                   help="LCC topic column recorded per-shard in the manifest for audit (default: topic_or_subject_gen)")
    # Dedup
    p.add_argument("--no-dedup", action="store_true",
                   help="Disable barcode-based dedup (default: dedup ON via likely_duplicates_barcodes_gen)")
    # Shard layout
    p.add_argument("--chars-per-shard", type=int, default=250_000_000,
                   help="Target characters per shard before flush (default: 250M, ~100MB compressed)")
    p.add_argument("--row-group-size", type=int, default=64,
                   help="Parquet row group size (default: 64)")
    # Diversity
    p.add_argument("--shuffle-buffer-gb", type=float, default=20.0,
                   help="Shuffle buffer size in GB of UTF-8 text (default: 20; tune to available RAM. "
                        "Must be >= longest pure source cluster to fully decorrelate it)")
    p.add_argument("--val-target", type=int, default=1000,
                   help="Approximate number of val books (hash divisor = EST_PASSING/val-target; default: 1000)")
    p.add_argument("--shuffle-seed", type=int, default=42, help="RNG seed for eviction (default: 42)")
    # Limits (smoke tests)
    p.add_argument("--max-shards", type=int, default=-1, help="Stop after N shards (-1 = unlimited)")
    p.add_argument("--max-rows", type=int, default=-1, help="Stop after N source rows (-1 = unlimited)")
    # Upload
    p.add_argument("--upload", action="store_true",
                   help="Upload the whole output dir to HF after processing (one-shot upload_large_folder)")
    p.add_argument("--upload-incremental", action="store_true",
                   help="Upload shards to HF in batches as they are written, then delete the "
                        "local copies (low local-disk footprint + durable across restarts)")
    p.add_argument("--upload-batch", type=int, default=50,
                   help="Shards per HF commit when --upload-incremental (default: 50). "
                        "HF caps commits at 128/hour, so one-commit-per-shard hits 429; "
                        "batching keeps commit rate far under the cap.")
    p.add_argument("--upload-only", action="store_true",
                   help="Skip processing; only upload an already-built output dir")
    p.add_argument("--repo-id", type=str, default="jbduran/think-institutional-books",
                   help="HF dataset repo id (created private if missing)")
    return p.parse_args()


def main():
    args = parse_args()

    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path)
        print(f"Loaded .env from {dotenv_path}")
    else:
        print("Note: no .env found; relying on environment HF_TOKEN")
    token = os.getenv("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN not set. Put it in .env at the repo root.")

    if args.upload_only:
        upload_to_hf(args.output_dir, args.repo_id, token)
        return

    process(args, token)

    if args.upload and not args.upload_incremental:
        upload_to_hf(args.output_dir, args.repo_id, token)


if __name__ == "__main__":
    main()
