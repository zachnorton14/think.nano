"""
Stream, filter, dedup, shuffle, and repackage `institutional/institutional-books-1.0`
into nanochat-compatible parquet shards.

Filters applied (all must pass; first match wins):
  - language_gen == "eng"
  - parsed year of date1_src (fallback date2_src) < --year-max (default 1930)
    rows where neither date parses are REJECTED (no leakage path for modern data)
  - English proportion in language_distribution_gen >= --min-english-proportion
    (default 0.90)
  - ocr_score_src >= --ocr-min and ocr_score_gen >= --ocr-min (default 90)
  - |ocr_score_src - ocr_score_gen| <= --ocr-disagreement-max (default 10)
  - text_analysis_gen[text_by_page_gen].tokenizability_score >=
    --min-tokenizability (default 95)
  - reject only pathological tiny fragments (default floors: 500 tokens,
    2,000 chars, 3 pages)

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

Bandwidth: only the columns needed for text, premium filtering, and audit metadata
are streamed via select_columns, skipping the redundant `text_by_page_src` raw OCR
copy.

Resume (durable across Colab session resets):
  Put --state-dir on durable storage (e.g. Google Drive) while keeping shards on
  fast /content. With --upload-incremental, shard barcodes are promoted into
  committed_written only after upload succeeds. Each uploaded batch includes a
  recovery manifest, so a crash after upload but before local state promotion can
  be recovered without overwriting remote shards. On resume the script RE-STREAMS
  FROM ROW 0 and skips any barcode already in committed_written.

Output layout (drop-in compatible with nanochat/dataset.py):
  <output_dir>/
    shard_00000.parquet         # train
    ...
    shard_NNNNN.parquet         # val (last lexicographic shard)
    .state.json                 # resume checkpoint (incl. committed_written)
    README.md                   # provenance + stats + topic breakdown
    manifest.json               # per-shard breakdown (incl. topic_distribution)
    audit_metadata.jsonl         # separate per-document audit metadata

Each shard parquet: single `text` string column, ZSTD-3, row_group_size=64,
chars_per_shard=250M, use_dictionary=False, write_statistics=False.

Schema (verified live via HF dataset_info):
  - text_by_page_gen: sequence(large_string)  <- joined with "\\n\\n" per book
  - language_gen, date1_src, date2_src, topic_or_subject_gen: string
  - ocr_score_src, ocr_score_gen: int32
  - barcode_src: string (primary key); likely_duplicates_barcodes_gen: sequence(string)

Usage:
    # Process to local SSD, keep shards
    python dev/dataset/repackage_institutional_books.py --output-dir /content/base_data_books

    # Process + incrementally upload each shard to HF, freeing local disk
    python dev/dataset/repackage_institutional_books.py --output-dir /content/base_data_books \
        --state-dir /content/drive/MyDrive/nanochat_state \
        --upload-incremental --repo-id jbduran/think-institutional-books-premium

    # Upload an already-built dir in one shot
    python dev/dataset/repackage_institutional_books.py --output-dir /content/base_data_books \
        --upload-only --repo-id jbduran/think-institutional-books-premium

Requires HF_TOKEN in .env (project root) with access to the gated dataset.
"""

import argparse
import json
import os
import random
import re
import shutil
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
from huggingface_hub import HfApi, hf_hub_download

try:
    from dotenv import find_dotenv, load_dotenv
except ImportError:
    def find_dotenv(*args, **kwargs):
        p = os.path.join(os.getcwd(), ".env")
        return p if os.path.exists(p) else ""

    def load_dotenv(path="", *args, **kwargs):
        if not path or not os.path.exists(path):
            return False
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
        return True


SOURCE_DATASET = "institutional/institutional-books-1.0"
SOURCE_SPLIT = "train"
REQUIRED_FILTER_COLUMNS = (
    "language_gen", "date1_src", "date2_src", "date_types_src",
    "ocr_score_src", "ocr_score_gen", "language_distribution_gen",
    "text_analysis_gen", "page_count_src", "token_count_o200k_base_gen",
)
DEDUP_COLUMNS = ("barcode_src", "likely_duplicates_barcodes_gen")
STATE_FILENAME = ".state.json"
README_FILENAME = "README.md"
MANIFEST_FILENAME = "manifest.json"
AUDIT_FILENAME = "audit_metadata.jsonl"
BATCH_DIRNAME = "_upload_batches"
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


def _date_type_invalid(row):
    """Conservatively reject MARC date types known to be bad for fixed-year filters."""
    v = row.get("date_types_src")
    if v is None:
        return False
    s = str(v).strip().lower()
    if not s:
        return False
    if "continuing" in s or "no attempt" in s:
        return True
    # MARC 008 date type c/d denote continuing resources; n is unknown dates.
    return s[0] in {"c", "d", "n", "|"}


def _language_proportion(row, language):
    dist = row.get("language_distribution_gen") or {}
    langs = dist.get("language") or dist.get("languages") or []
    props = dist.get("proportion") or []
    for lang, prop in zip(langs, props):
        if lang == language:
            try:
                return float(prop) / (100.0 if float(prop) > 1.0 else 1.0)
            except (TypeError, ValueError):
                return None
    return 0.0 if langs else None


def _text_analysis(row, text_column):
    analysis = row.get("text_analysis_gen") or {}
    if text_column in analysis and isinstance(analysis[text_column], dict):
        return analysis[text_column]
    if "text_by_page_gen" in analysis and isinstance(analysis["text_by_page_gen"], dict):
        return analysis["text_by_page_gen"]
    return analysis if isinstance(analysis, dict) else {}


def _to_int(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def classify_row(row, args):
    """Return ('pass', info_dict) or ('reject', reason_str)."""
    if row.get("language_gen") != "eng":
        return "reject", "language"

    eng_prop = _language_proportion(row, "eng")
    if eng_prop is None:
        return "reject", "language_distribution_missing"
    if eng_prop < args.min_english_proportion:
        return "reject", "language_low_english_proportion"

    if args.reject_invalid_date_types and _date_type_invalid(row):
        return "reject", "date_type_invalid"

    year, year_src = resolve_year(row)
    if year is None:
        return "reject", "year_unparseable"  # no leakage path for undated rows
    if year >= args.year_max:
        return "reject", "year_too_recent"

    src = _to_float(row.get("ocr_score_src"))
    gen = _to_float(row.get("ocr_score_gen"))
    if src is None or gen is None:
        return "reject", "ocr_missing"
    if src < args.ocr_min or gen < args.ocr_min:
        return "reject", "ocr_low"
    ocr_disagreement = abs(src - gen)
    if ocr_disagreement > args.ocr_disagreement_max:
        return "reject", "ocr_disagree"

    ta = _text_analysis(row, args.text_column)
    tokenizability = _to_float(ta.get("tokenizability_score"))
    if tokenizability is None:
        return "reject", "tokenizability_missing"
    if tokenizability < args.min_tokenizability:
        return "reject", "tokenizability_low"

    token_count = _to_int(row.get("token_count_o200k_base_gen"))
    char_count = _to_int(ta.get("char_count"))
    page_count = _to_int(row.get("page_count_src"))
    sentence_count = _to_int(ta.get("sentence_count"))
    if token_count is None or token_count < args.min_tokens:
        return "reject", "too_few_tokens"
    if char_count is None or char_count < args.min_chars:
        return "reject", "too_few_chars"
    if page_count is None or page_count < args.min_pages:
        return "reject", "too_few_pages"
    if sentence_count is None or (
        sentence_count < args.min_sentences
        and token_count < args.min_tokens_for_sentence_exception
    ):
        return "reject", "too_few_sentences"

    return "pass", {
        "year_src": year_src,
        "resolved_year": year,
        "english_proportion": eng_prop,
        "ocr_score_src": src,
        "ocr_score_gen": gen,
        "ocr_disagreement": ocr_disagreement,
        "tokenizability_score": tokenizability,
        "token_count_o200k_base_gen": token_count,
        "page_count_src": page_count,
        "char_count": char_count,
        "word_count": _to_int(ta.get("word_count")),
        "sentence_count": sentence_count,
    }


def classify_legacy_row(row, args):
    """The old broad filter, for dry-run pass-rate comparison only."""
    if row.get("language_gen") != "eng":
        return "reject", "language"
    year, _ = resolve_year(row)
    if year is None:
        return "reject", "year_unparseable"
    if year >= args.year_max:
        return "reject", "year_too_recent"
    src = _to_float(row.get("ocr_score_src"))
    gen = _to_float(row.get("ocr_score_gen"))
    if src is None or gen is None:
        return "reject", "ocr_missing"
    if src <= 85 or gen <= 85:
        return "reject", "ocr_low"
    if abs(src - gen) >= 15:
        return "reject", "ocr_disagree"
    return "pass", {}


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


def state_path(state_dir):
    return os.path.join(state_dir, STATE_FILENAME)


def audit_path(state_dir):
    return os.path.join(state_dir, AUDIT_FILENAME)


def load_state(state_dir):
    p = state_path(state_dir)
    if not os.path.exists(p):
        return None
    with open(p, "r") as f:
        return json.load(f)


def save_state_atomic(state_dir, state):
    os.makedirs(state_dir, exist_ok=True)
    def _w(tmp):
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2)
    _atomic_write(state_path(state_dir), _w)


def append_audit_records(state_dir, records):
    if not records:
        return
    os.makedirs(state_dir, exist_ok=True)
    with open(audit_path(state_dir), "a") as f:
        for record in records:
            f.write(json.dumps(record, sort_keys=True) + "\n")


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


def _batch_manifest_name(records):
    first = records[0]["index"]
    last = records[-1]["index"]
    return f"{BATCH_DIRNAME}/batch_{first:05d}_{last:05d}.json"


def write_batch_manifest(output_dir, records):
    rel = _batch_manifest_name(records)
    path = os.path.join(output_dir, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "source_dataset": SOURCE_DATASET,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }
    def _w(tmp):
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=2)
    _atomic_write(path, _w)
    return rel


def upload_batch_with_manifest(api, repo_id, output_dir, records):
    """Upload a batch of shard files and a recovery manifest in ONE commit.

    Batching is the key fix for HF's 128-commits/hour cap: one commit per
    batch instead of one per shard. The batch manifest lets a later run promote
    already-uploaded shards into durable state instead of overwriting them.
    """
    if not records:
        return
    filenames = [r["filename"] for r in records]
    manifest = write_batch_manifest(output_dir, records)
    allow_patterns = filenames + [manifest]
    _with_upload_retry(
        lambda: api.upload_folder(
            folder_path=output_dir,
            repo_id=repo_id,
            repo_type="dataset",
            allow_patterns=allow_patterns,
            commit_message=f"Add {len(filenames)} shard(s): {filenames[0]}..{filenames[-1]}",
        ),
        what=f"batch[{filenames[0]}..{filenames[-1]}]",
    )
    for fn in filenames + [manifest]:
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
            "min_english_proportion": args.min_english_proportion,
            "year_max_exclusive": args.year_max,
            "reject_invalid_date_types": args.reject_invalid_date_types,
            "ocr_min_inclusive": args.ocr_min,
            "ocr_disagreement_max_inclusive": args.ocr_disagreement_max,
            "min_tokenizability": args.min_tokenizability,
            "min_tokens": args.min_tokens,
            "min_chars": args.min_chars,
            "min_pages": args.min_pages,
            "min_sentences": args.min_sentences,
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
        "audit_metadata": AUDIT_FILENAME,
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
    val_count = sum(1 for s in shard_records if s.get("is_val"))
    train_count = max(0, totals["num_shards"] - val_count)
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
| `language_distribution_gen` | English proportion `>= {args.min_english_proportion}` |
| `date1_src` → `date2_src` fallback | parsed year `< {args.year_max}` (undated REJECTED; invalid date types rejected: `{args.reject_invalid_date_types}`) |
| `ocr_score_src`| `>= {args.ocr_min}` |
| `ocr_score_gen`| `>= {args.ocr_min}` |
| OCR agreement  | `\\|src - gen\\| <= {args.ocr_disagreement_max}` |
| `text_analysis_gen.text_by_page_gen.tokenizability_score` | `>= {args.min_tokenizability}` |
| tiny fragments | tokens `>= {args.min_tokens}`, chars `>= {args.min_chars}`, pages `>= {args.min_pages}`, sentences `>= {args.min_sentences}` unless token exception applies |

## Dedup

{"Enabled" if not args.no_dedup else "DISABLED (--no-dedup)"} — via `likely_duplicates_barcodes_gen` barcode claiming (first-seen representative kept).

## Diversity strategy

- **Single shuffle buffer**: training books accumulate in a UTF-8-bytes buffer; when it exceeds **{args.shuffle_buffer_gb} GB** a uniformly random book is evicted to the current output shard. Decorrelates the source's library-archive clustering while preserving the corpus's natural topic distribution. Buffer must be ≥ the longest pure cluster to fully break it.
- **Validation split**: deterministic by barcode hash — a book is val iff `crc32(barcode) % {val_divisor} == 0` (~`{args.val_target}` books). Resume-stable; written as the last lexicographic shard.

## Stats

- Source rows seen: **{totals['rows_seen']:,}**
- Rows passed filter + dedup: **{totals['rows_passed']:,}** ({pass_rate:.2f}% of seen)
- Total characters written: **{totals['total_chars']:,}**
- Total shards: **{totals['num_shards']:,}**  (train: {train_count}, val: {val_count})
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
in `manifest.json` (`shards[].topic_distribution`). Per-document audit metadata
lives separately in `{AUDIT_FILENAME}`; training shards remain text-only.

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


SHARD_RE = re.compile(r"shard_(\d+)\.parquet$")
BATCH_RE = re.compile(rf"{BATCH_DIRNAME}/batch_(\d+)_(\d+)\.json$")


def list_remote_indices(api, repo_id):
    files = api.list_repo_files(repo_id=repo_id, repo_type="dataset")
    shard_indices = set()
    batch_files = []
    for path in files:
        m = SHARD_RE.search(path)
        if m:
            shard_indices.add(int(m.group(1)))
        if BATCH_RE.search(path):
            batch_files.append(path)
    return shard_indices, sorted(batch_files)


def promote_records(state, committed, records, state_dir):
    if not records:
        return
    records = sorted(records, key=lambda r: r["index"])
    expected = state["shard_index"]
    for record in records:
        if record["index"] != expected:
            raise SystemExit(
                f"FATAL: cannot promote {record['filename']}; expected shard index "
                f"{expected}, got {record['index']}."
            )
        state["shards"].append({
            k: v for k, v in record.items()
            if k not in ("barcodes", "audit_records")
        })
        state["total_chars"] += record["num_chars"]
        state["shard_index"] = record["index"] + 1
        state["last_updated"] = datetime.now(timezone.utc).isoformat()
        for t, c in record.get("topic_distribution", {}).items():
            state["topic_distribution_overall"][t] = state["topic_distribution_overall"].get(t, 0) + c
        committed.update(record.get("barcodes", []))
        state["committed_written"] = sorted(committed)
        expected += 1
    save_state_atomic(state_dir, state)
    for record in records:
        append_audit_records(state_dir, record.get("audit_records", []))


def recover_remote_batches(api, repo_id, token, state, committed, state_dir):
    remote_indices, batch_files = list_remote_indices(api, repo_id)
    if not remote_indices:
        return remote_indices

    promoted_any = True
    while promoted_any:
        promoted_any = False
        _, batch_files = list_remote_indices(api, repo_id)
        for path in batch_files:
            m = BATCH_RE.search(path)
            if not m:
                continue
            start = int(m.group(1))
            if start != state["shard_index"]:
                continue
            local = hf_hub_download(
                repo_id=repo_id,
                filename=path,
                repo_type="dataset",
                token=token,
            )
            with open(local, "r") as f:
                payload = json.load(f)
            records = payload.get("records", [])
            print(f"Recovering uploaded batch metadata {path} into durable state...")
            promote_records(state, committed, records, state_dir)
            promoted_any = True
            break

    remote_indices, _ = list_remote_indices(api, repo_id)
    if remote_indices and max(remote_indices) >= state["shard_index"]:
        raise SystemExit(
            "FATAL: Hugging Face repo contains shard indexes ahead of local state "
            f"(max remote shard={max(remote_indices):05d}, local next shard="
            f"{state['shard_index']:05d}). Refusing to overwrite. Use a clean new "
            "repo, or recover/delete the remote shards intentionally."
        )
    return remote_indices


def make_audit_record(row, quality, shard_index, is_val):
    dups = row.get("likely_duplicates_barcodes_gen") or []
    return {
        "barcode_src": row.get("barcode_src"),
        "title_src": row.get("title_src"),
        "author_src": row.get("author_src"),
        "date1_src": row.get("date1_src"),
        "date2_src": row.get("date2_src"),
        "date_types_src": row.get("date_types_src"),
        "resolved_year": quality["resolved_year"],
        "language_gen": row.get("language_gen"),
        "english_proportion": quality["english_proportion"],
        "ocr_score_src": quality["ocr_score_src"],
        "ocr_score_gen": quality["ocr_score_gen"],
        "ocr_disagreement": quality["ocr_disagreement"],
        "tokenizability_score": quality["tokenizability_score"],
        "token_count_o200k_base_gen": quality["token_count_o200k_base_gen"],
        "page_count_src": quality["page_count_src"],
        "char_count": quality["char_count"],
        "word_count": quality["word_count"],
        "sentence_count": quality["sentence_count"],
        "topic_or_subject_gen": row.get("topic_or_subject_gen"),
        "topic_or_subject_score_gen": row.get("topic_or_subject_score_gen"),
        "likely_duplicate_count": len(dups),
        "output_shard_index": shard_index,
        "output_shard_filename": f"shard_{shard_index:05d}.parquet",
        "is_val": is_val,
    }


def _profile_args(args, *, name):
    profile = argparse.Namespace(**vars(args))
    if name == "premium_strict":
        profile.ocr_min = 90.0
        profile.ocr_disagreement_max = 10.0
        profile.min_tokenizability = 95.0
        profile.min_english_proportion = 0.95
    elif name == "relaxed_premium":
        profile.ocr_min = 90.0
        profile.ocr_disagreement_max = 10.0
        profile.min_tokenizability = 93.0
        profile.min_english_proportion = 0.90
    return profile


def dry_run_stats(ds, args):
    profiles = {
        "legacy_old_filter": None,
        "premium_strict": _profile_args(args, name="premium_strict"),
        "relaxed_premium": _profile_args(args, name="relaxed_premium"),
    }
    stats = {
        name: {
            "rows_passed": 0,
            "tokens": 0,
            "pages": 0,
            "rejections": Counter(),
            "topics": Counter(),
            "decades": Counter(),
        }
        for name in profiles
    }
    seen_by_profile = {name: set() for name in profiles}
    rows_seen = 0
    for row in ds:
        rows_seen += 1
        for name, profile in profiles.items():
            if name == "legacy_old_filter":
                verdict, reason = classify_legacy_row(row, args)
            else:
                verdict, reason = classify_row(row, profile)
            if verdict == "reject":
                stats[name]["rejections"][reason] += 1
                continue
            if not args.no_dedup and is_duplicate(row, seen_by_profile[name]):
                stats[name]["rejections"]["duplicate"] += 1
                continue
            if not args.no_dedup:
                claim_barcodes(row, seen_by_profile[name])
            stats[name]["rows_passed"] += 1
            stats[name]["tokens"] += _to_int(row.get("token_count_o200k_base_gen")) or 0
            stats[name]["pages"] += _to_int(row.get("page_count_src")) or 0
            stats[name]["topics"][row.get(args.topic_column) or UNKNOWN_TOPIC] += 1
            year, _ = resolve_year(row)
            if year is not None:
                stats[name]["decades"][(year // 10) * 10] += 1
        if args.max_rows > 0 and rows_seen >= args.max_rows:
            break
        if rows_seen % 10000 == 0:
            print(f"dry-run scanned {rows_seen:,} rows...")

    print("\n=== Dry-run filter comparison ===")
    print(f"Rows seen: {rows_seen:,}")
    for name, s in stats.items():
        pass_rate = 100.0 * s["rows_passed"] / max(1, rows_seen)
        print(f"\n[{name}]")
        print(f"  rows_passed={s['rows_passed']:,} ({pass_rate:.2f}%)")
        print(f"  tokens={s['tokens']:,}")
        print(f"  pages={s['pages']:,}")
        print(f"  top_rejections={s['rejections'].most_common(12)}")
        print(f"  top_topics={s['topics'].most_common(10)}")
        print(f"  top_decades={s['decades'].most_common(10)}")


# -----------------------------------------------------------------------------
# Main processing loop

def process(args, token):
    os.makedirs(args.output_dir, exist_ok=True)
    args.state_dir = args.state_dir or args.output_dir
    os.makedirs(args.state_dir, exist_ok=True)

    val_divisor = max(1, round(EST_PASSING / args.val_target))
    buf_limit = int(args.shuffle_buffer_gb * (1024 ** 3))
    print(f"val_divisor={val_divisor} (target ~{args.val_target} val books), "
          f"shuffle buffer limit={args.shuffle_buffer_gb} GB ({buf_limit:,} bytes)")
    print(f"state_dir={args.state_dir}")

    # Incremental-upload setup
    api = None
    if args.upload_incremental:
        api = HfApi(token=token)
        print(f"Incremental upload enabled -> {args.repo_id} (created private if missing)")
        api.create_repo(repo_id=args.repo_id, repo_type="dataset", private=True, exist_ok=True)

    state = load_state(args.state_dir)
    if state is None:
        state = {
            "shard_index": 0, "rows_seen": 0, "rows_passed": 0, "total_chars": 0,
            "rejections": {}, "pass_by_year_source": {},
            "topic_distribution_overall": {}, "shards": [],
            "committed_written": [], "last_updated": None, "complete": False,
        }
    else:
        if state.get("complete") and not args.force_new_run:
            raise SystemExit(
                "FATAL: this state is marked complete. Refusing to append. "
                "Use a fresh --state-dir/--output-dir or pass --force-new-run."
            )
        print(f"Resuming: shard_index={state['shard_index']}, "
              f"rows_passed={state['rows_passed']:,}, "
              f"committed={len(state.get('committed_written', [])):,}")
        state.setdefault("pass_by_year_source", {})
        state.setdefault("topic_distribution_overall", {})
        state.setdefault("committed_written", [])
        state.setdefault("complete", False)

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
        recover_remote_batches(api, args.repo_id, token, state, committed, args.state_dir)
        if recover:
            raise SystemExit(
                "FATAL: found local shard files older than durable state, but no "
                "batch metadata is available to safely recover barcodes. Refusing "
                "to upload ambiguous local shards."
            )

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

    # Column projection — stream text plus filter/audit metadata, skipping raw OCR.
    needed = {
        "barcode_src",
        "title_src",
        "author_src",
        "date1_src",
        "date2_src",
        "date_types_src",
        "language_gen",
        "language_distribution_gen",
        "ocr_score_src",
        "ocr_score_gen",
        "text_analysis_gen",
        "page_count_src",
        "token_count_o200k_base_gen",
        args.topic_column,
        "topic_or_subject_score_gen",
    }
    if not args.dry_run_stats:
        needed.add(args.text_column)
    if not args.no_dedup:
        needed.update(DEDUP_COLUMNS)
    try:
        ds = ds.select_columns(sorted(needed))
        print(f"Streaming only {len(needed)} columns: {sorted(needed)}")
    except Exception as e:
        print(f"select_columns failed ({e}); streaming all columns (slower).")

    if args.dry_run_stats:
        dry_run_stats(ds, args)
        return

    # NOTE: NO ds.skip on resume. The shuffle buffer holds books from arbitrary
    # source positions, so a row-counter skip would drop buffered-but-unwritten
    # books. We re-stream from row 0 and rely on `committed` to skip already-written.

    # In-flight state
    schema_verified = False
    has_topic_column = True
    shard_index = state["shard_index"]
    shard_docs, shard_topics, shard_barcodes, shard_audit_records = [], [], [], []
    shard_chars = 0
    buffer = []        # list of (text_bytes, topic, barcode, audit_record)
    buf_bytes = 0
    val_buffer = []    # list of (text_bytes, topic, barcode, audit_record), held to end
    seen_barcodes = set()  # in-memory dedup set, rebuilt this stream (never persisted)
    run_rows_seen = 0
    rng = random.Random(args.shuffle_seed)
    t_start = time.time()
    t_last_log = t_start
    pending_records = []  # shard records written locally but not yet uploaded/promoted
    interrupted = False
    stopped_early = False

    def add_to_shard(text, topic, barcode, audit_record):
        nonlocal shard_chars
        shard_docs.append(text)
        shard_topics.append(topic)
        shard_barcodes.append(barcode)
        shard_audit_records.append(audit_record)
        shard_chars += len(text)

    def flush_uploads():
        """Upload pending shards to HF in ONE commit, then promote durable state."""
        if not pending_records:
            return
        if api is not None:
            upload_batch_with_manifest(api, args.repo_id, args.output_dir, list(pending_records))
            print(f"  uploaded batch of {len(pending_records)} shard(s) in 1 commit "
                  f"(rate-limit safe)")
        promote_records(state, committed, list(pending_records), args.state_dir)
        pending_records.clear()

    def flush_shard():
        nonlocal shard_index, shard_chars
        if not shard_docs:
            return
        # 1) shard durable on disk
        filename, _ = write_shard(
            args.output_dir, shard_index, shard_docs, args.row_group_size
        )
        topic_counts = dict(Counter(shard_topics))
        record = {
            "index": shard_index, "filename": filename,
            "num_docs": len(shard_docs), "num_chars": shard_chars,
            "topic_distribution": topic_counts,
            "barcodes": list(shard_barcodes),
            "audit_records": list(shard_audit_records),
        }
        top3 = sorted(topic_counts.items(), key=lambda x: -x[1])[:3]
        print(f"WROTE {filename} | docs={len(shard_docs):,} chars={shard_chars:,} top3={top3}")
        pending_records.append(record)
        if api is None or len(pending_records) >= args.upload_batch:
            flush_uploads()
        shard_index += 1
        shard_docs.clear()
        shard_topics.clear()
        shard_barcodes.clear()
        shard_audit_records.clear()
        shard_chars = 0

    def maybe_flush():
        if shard_chars >= args.chars_per_shard:
            flush_shard()

    def evict_one():
        """Evict a uniformly random book from the buffer into the current shard."""
        nonlocal buf_bytes
        i = rng.randrange(len(buffer))
        buffer[i], buffer[-1] = buffer[-1], buffer[i]  # O(1) swap-and-pop
        tb, topic, bc, audit_record = buffer.pop()
        buf_bytes -= len(tb)
        audit_record["output_shard_index"] = shard_index
        audit_record["output_shard_filename"] = f"shard_{shard_index:05d}.parquet"
        add_to_shard(tb.decode("utf-8"), topic, bc, audit_record)
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

            verdict, quality_or_reason = classify_row(row, args)
            if verdict == "reject":
                state["rejections"][quality_or_reason] = state["rejections"].get(quality_or_reason, 0) + 1
            else:
                quality = quality_or_reason
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
                            year_src = quality["year_src"]
                            state["pass_by_year_source"][year_src] = state["pass_by_year_source"].get(year_src, 0) + 1
                            state["rows_passed"] += 1
                            tb = text.encode("utf-8")
                            audit_record = make_audit_record(row, quality, shard_index, is_val(bc, val_divisor))
                            if is_val(bc, val_divisor):
                                val_buffer.append((tb, topic, bc, audit_record))
                            else:
                                buffer.append((tb, topic, bc, audit_record))
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
                stopped_early = True
                break
            if args.max_rows > 0 and (state["rows_seen"] + run_rows_seen) >= args.max_rows:
                print(f"Reached --max-rows={args.max_rows}, stopping.")
                stopped_early = True
                break

    except KeyboardInterrupt:
        print(f"\nKeyboardInterrupt: discarding {len(buffer)} buffered docs. "
              f"Resume re-streams + skips committed.")
        interrupted = True

    # Update rows_seen once at the end (stats only — not used for resume)
    state["rows_seen"] += run_rows_seen

    # Drain the shuffle buffer in random order (only if not stopped by --max-shards)
    should_finalize = not interrupted and not (
        args.max_shards > 0 and shard_index >= args.max_shards
    )

    if should_finalize:
        if buffer:
            print(f"Draining {len(buffer):,} buffered books (random order)...")
        while buffer:
            evict_one()
            if args.max_shards > 0 and shard_index >= args.max_shards:
                break
        if shard_docs:
            flush_shard()

    # Val (hash-selected) -> final (last lexicographic) shard
    if val_buffer and should_finalize:
        val_docs = [tb.decode("utf-8") for tb, _, _, _ in val_buffer]
        val_topics = [top for _, top, _, _ in val_buffer]
        val_barcodes = [bc for _, _, bc, _ in val_buffer]
        val_audit_records = []
        for _, _, _, audit_record in val_buffer:
            audit_record["output_shard_index"] = shard_index
            audit_record["output_shard_filename"] = f"shard_{shard_index:05d}.parquet"
            val_audit_records.append(audit_record)
        val_chars = sum(len(d) for d in val_docs)
        filename, _ = write_shard(args.output_dir, shard_index, val_docs, args.row_group_size)
        topic_counts = dict(Counter(val_topics))
        pending_records.append({
            "index": shard_index, "filename": filename,
            "num_docs": len(val_docs), "num_chars": val_chars,
            "topic_distribution": topic_counts, "is_val": True,
            "barcodes": val_barcodes, "audit_records": val_audit_records,
        })
        print(f"WROTE VAL {filename} | docs={len(val_docs):,} chars={val_chars:,}")
        shard_index += 1

    # Flush any remaining queued shards (incl. val) as a final batch commit
    if pending_records:
        flush_uploads()
    if should_finalize:
        state["complete"] = True
        state["last_updated"] = datetime.now(timezone.utc).isoformat()
        save_state_atomic(args.state_dir, state)

    totals = {
        "rows_seen": state["rows_seen"], "rows_passed": state["rows_passed"],
        "total_chars": state["total_chars"], "num_shards": len(state["shards"]),
        "rejections": state["rejections"],
        "pass_by_year_source": state["pass_by_year_source"],
        "topic_distribution_overall": state["topic_distribution_overall"],
        "complete": state.get("complete", False),
        "state_dir": args.state_dir,
        "audit_metadata": AUDIT_FILENAME,
    }
    update_manifest(args.output_dir, args, state["shards"], totals, val_divisor)
    write_readme(args.output_dir, args, totals, state["shards"], val_divisor)
    if os.path.exists(audit_path(args.state_dir)):
        shutil.copyfile(audit_path(args.state_dir), os.path.join(args.output_dir, AUDIT_FILENAME))

    # Push metadata files when incrementally uploading (shards already uploaded)
    if api is not None:
        present = [m for m in (MANIFEST_FILENAME, README_FILENAME, AUDIT_FILENAME)
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
    val_count = sum(1 for s in state["shards"] if s.get("is_val"))
    print(f"Shards:      {totals['num_shards']} (train {totals['num_shards'] - val_count}, val {val_count})")
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
    p.add_argument("--state-dir", type=str, default=None,
                   help="Durable state/audit dir (default: --output-dir; use Drive on Colab)")
    # Filters
    p.add_argument("--year-max", type=int, default=1930,
                   help="Exclusive upper bound on parsed year (default: 1930)")
    p.add_argument("--ocr-min", type=float, default=90.0,
                   help="Inclusive lower bound on each OCR score (default: 90, premium)")
    p.add_argument("--ocr-disagreement-max", type=float, default=10.0,
                   help="Inclusive upper bound on |src - gen| OCR disagreement (default: 10)")
    p.add_argument("--min-english-proportion", type=float, default=0.90,
                   help="Minimum English share in language_distribution_gen (default: 0.90)")
    p.add_argument("--min-tokenizability", type=float, default=95.0,
                   help="Minimum post-processed tokenizability score (default: 95)")
    p.add_argument("--min-tokens", type=int, default=500,
                   help="Reject pathological fragments below this o200k token count (default: 500)")
    p.add_argument("--min-chars", type=int, default=2_000,
                   help="Reject pathological fragments below this postprocessed char count (default: 2000)")
    p.add_argument("--min-pages", type=int, default=3,
                   help="Reject pathological fragments below this page count (default: 3)")
    p.add_argument("--min-sentences", type=int, default=20,
                   help="Reject very short sentence-count fragments unless token exception applies (default: 20)")
    p.add_argument("--min-tokens-for-sentence-exception", type=int, default=2_000,
                   help="Allow low sentence_count only when token count is at least this value (default: 2000)")
    p.add_argument("--reject-invalid-date-types", action=argparse.BooleanOptionalAction, default=True,
                   help="Reject MARC date types that imply continuing/unknown dates (default: true)")
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
    p.add_argument("--dry-run-stats", action="store_true",
                   help="Metadata-only filter comparison; writes no shards")
    # Upload
    p.add_argument("--upload", action="store_true",
                   help="Upload the whole output dir to HF after processing (one-shot upload_large_folder)")
    p.add_argument("--upload-incremental", action="store_true",
                   help="Upload shards to HF in batches as they are written, then delete the "
                        "local copies. Use --state-dir on durable storage for restart safety.")
    p.add_argument("--upload-batch", type=int, default=50,
                   help="Shards per HF commit when --upload-incremental (default: 50). "
                        "HF caps commits at 128/hour, so one-commit-per-shard hits 429; "
                        "batching keeps commit rate far under the cap.")
    p.add_argument("--upload-only", action="store_true",
                   help="Skip processing; only upload an already-built output dir")
    p.add_argument("--repo-id", type=str, default="jbduran/think-institutional-books",
                   help="HF dataset repo id (created private if missing)")
    p.add_argument("--force-new-run", action="store_true",
                   help="Allow running against a state marked complete (use with care)")
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
