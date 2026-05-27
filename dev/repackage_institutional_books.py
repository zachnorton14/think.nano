"""
Stream, filter, topic-balance, and repackage `institutional/institutional-books-1.0`
into nanochat-compatible parquet shards.

Filters applied (all must pass; first match wins):
  - language_gen == "eng"
  - parsed year of date1_src (fallback date2_src) < --year-max (default 1930)
    rows where neither date parses are REJECTED (no leakage path for modern data)
  - ocr_score_src  > --ocr-min (default 85)
  - ocr_score_gen  > --ocr-min (default 85)
  - |ocr_score_src - ocr_score_gen| < --ocr-disagreement-max (default 15)

Diversity strategy (three independent mechanisms):
  1. Per-topic deques keyed on `topic_or_subject_gen` (BERT-classified LCC topic).
     Yielding is round-robin biased by least-recently-yielded topic — when a long
     library cluster (e.g. 20K LAW books in a row) arrives, the LAW deque caps,
     then the moment any non-LAW row appears it gets yielded preferentially.
  2. Within-topic random shuffle on yield (swap-and-pop a random index).
  3. Reservoir-sampled validation set: K rows uniformly sampled from the entire
     filtered stream; written as the last lexicographic shard so it becomes val
     per nanochat's last-file convention.

Output layout (drop-in compatible with nanochat/dataset.py):
  <output_dir>/
    shard_00000.parquet         # train
    shard_00001.parquet         # train
    ...
    shard_NNNNN.parquet         # val (last lexicographic shard, from reservoir)
    .state.json                 # resume checkpoint
    .val_reservoir.parquet      # in-flight reservoir snapshot (allows resume)
    README.md                   # provenance + stats + topic breakdown
    manifest.json               # per-shard breakdown (incl. topic_distribution)

Each shard parquet: single `text` string column, ZSTD-3, row_group_size=64,
chars_per_shard=250M, use_dictionary=False, write_statistics=False.

Schema (verified live via HF dataset_info before this script was written):
  - text_by_page_gen: sequence(large_string)  ← joined with "\\n\\n" per book
  - language_gen, date1_src, date2_src: string
  - ocr_score_src, ocr_score_gen: int32
  - topic_or_subject_gen: string (BERT-classified LCC, 20 values)

Resume:
  Re-running with the same --output-dir picks up where it left off via
  .state.json (only updated on successful shard flush, so partial in-flight
  buffers are safely re-processed). The val reservoir is also persisted to
  .val_reservoir.parquet on each flush so it survives session restarts.

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
import random
import re
import signal
import sys
import time
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone

import huggingface_hub
import pyarrow as pa
import pyarrow.parquet as pq
from datasets import load_dataset
from dotenv import find_dotenv, load_dotenv
from huggingface_hub import HfApi


SOURCE_DATASET = "institutional/institutional-books-1.0"
SOURCE_SPLIT = "train"
# Columns required to filter; topic column is checked separately (graceful fallback)
REQUIRED_FILTER_COLUMNS = (
    "language_gen", "date1_src", "date2_src", "ocr_score_src", "ocr_score_gen",
)
STATE_FILENAME = ".state.json"
VAL_RESERVOIR_FILENAME = ".val_reservoir.parquet"
README_FILENAME = "README.md"
MANIFEST_FILENAME = "manifest.json"
UNKNOWN_TOPIC = "UNKNOWN"


# -----------------------------------------------------------------------------
# Filtering

_YEAR_RE = re.compile(r"\d{4}")


def parse_year(date_str):
    """Extract a plausible 4-digit year from a MARC date string.

    Returns int year in [1000, 2100], or None if no usable year found.
    MARC date fields contain artifacts like '18uu', '9999', '0000', '    '.
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
    """Return ('pass', year_src_field) or ('reject', reason_str).

    `year_src_field` is either 'date1_src' or 'date2_src' depending on which
    parsed successfully — tracked so we can report fallback recovery rate.
    """
    if row.get("language_gen") != "eng":
        return "reject", "language"

    year, year_src = resolve_year(row)
    if year is None:
        # No leakage path — undated rows always reject. Modern data could
        # slip through if we kept these.
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

    return "pass", year_src


def extract_text(row, col_name):
    """Extract the book's text from the source column.

    text_by_page_gen is a list of page strings — join with double newline so
    paragraph boundaries between pages are preserved as sentence delimiters
    for the downstream tokenizer. If the column happens to be a single string
    (e.g. legacy `text`), return as-is.
    """
    val = row.get(col_name)
    if val is None:
        return None
    if isinstance(val, list):
        return "\n\n".join(str(p) for p in val if p)
    if isinstance(val, str):
        return val
    return None


# -----------------------------------------------------------------------------
# State (resume)

def state_path(output_dir):
    return os.path.join(output_dir, STATE_FILENAME)


def load_state(output_dir):
    p = state_path(output_dir)
    if not os.path.exists(p):
        return None
    with open(p, "r") as f:
        return json.load(f)


def save_state_atomic(output_dir, state):
    p = state_path(output_dir)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, p)


# -----------------------------------------------------------------------------
# Val reservoir persistence (sidecar parquet for crash-safe resume)

def val_reservoir_path(output_dir):
    return os.path.join(output_dir, VAL_RESERVOIR_FILENAME)


def save_val_reservoir(output_dir, val_reservoir):
    if not val_reservoir:
        return
    p = val_reservoir_path(output_dir)
    tmp = p + ".tmp"
    texts = [t for t, _ in val_reservoir]
    topics = [top for _, top in val_reservoir]
    table = pa.Table.from_pydict({"text": texts, "topic": topics})
    pq.write_table(table, tmp, compression="zstd", compression_level=3,
                   use_dictionary=False, write_statistics=False)
    os.replace(tmp, p)


def load_val_reservoir(output_dir):
    p = val_reservoir_path(output_dir)
    if not os.path.exists(p):
        return []
    table = pq.read_table(p)
    texts = table.column("text").to_pylist()
    topics = table.column("topic").to_pylist()
    return list(zip(texts, topics))


# -----------------------------------------------------------------------------
# Shard writing

def write_shard(output_dir, shard_index, docs, row_group_size):
    """Write a single shard. Atomic via .tmp + rename. Single `text` column only."""
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
            "undated_rows_rejected": True,
        },
        "diversity": {
            "topic_column": args.topic_column,
            "topic_balance_enabled": not args.no_topic_balance,
            "per_topic_buffer_cap": args.per_topic_buffer_cap,
            "global_buffer_cap": args.global_buffer_cap,
            "val_reservoir_size": args.val_reservoir_size,
            "shuffle_seed": args.shuffle_seed,
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


def _format_topic_table(topic_counts):
    if not topic_counts:
        return "  (no topic data)"
    total = sum(topic_counts.values())
    lines = []
    for t, c in sorted(topic_counts.items(), key=lambda x: -x[1]):
        pct = 100.0 * c / total
        lines.append(f"  - `{t}`: {c:,} ({pct:.2f}%)")
    return "\n".join(lines)


def write_readme(output_dir, args, totals, shard_records):
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
repo is intended to be **private** and is shared only with users who themselves
have been granted access to the source dataset.

## Filters

| Field | Rule |
|---|---|
| `language_gen` | `== "eng"` |
| `date1_src` → `date2_src` fallback | parsed year `< {args.year_max}` (undated REJECTED) |
| `ocr_score_src`| `> {args.ocr_min}` |
| `ocr_score_gen`| `> {args.ocr_min}` |
| OCR agreement  | `\\|src - gen\\| < {args.ocr_disagreement_max}` |

## Diversity strategy

- **Topic-balanced yield**: per-topic deques (cap {args.per_topic_buffer_cap}/topic, {args.global_buffer_cap} global) with least-recently-yielded round-robin. Routed via `{args.topic_column}`. {"Enabled." if not args.no_topic_balance else "DISABLED (--no-topic-balance)."}
- **In-buffer shuffle**: random swap-and-pop within each topic deque.
- **Val reservoir**: {args.val_reservoir_size} rows uniformly sampled from the entire filtered stream via reservoir sampling, written as the last lexicographic shard (val per nanochat convention).

## Stats

- Source rows seen: **{totals['rows_seen']:,}**
- Rows passed filter: **{totals['rows_passed']:,}** ({pass_rate:.2f}% pass rate)
- Total characters written: **{totals['total_chars']:,}**
- Total shards: **{totals['num_shards']:,}**  (train: {train_count}, val: 1)
- Last shard (val): `{last_shard}` — uniform sample from the entire filtered corpus

### Rejections by reason
{rejection_lines if rejection_lines else "  (none)"}

### Pass-by-year-source (date1_src vs date2_src fallback recovery)
{year_src_lines}

### Overall topic distribution
{topic_table}

## Schema

Single string column named `text`. ZSTD-3 compressed, row-group size {args.row_group_size}.
Drop-in compatible with `nanochat/dataset.py` (which reads only the `text` column
and treats the last lexicographic shard as the validation split).

Per-shard topic distribution is in `manifest.json` (`shards[].topic_distribution`)
so diversity can be audited without re-reading text bodies.

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
    --row-group-size {args.row_group_size} \\
    --per-topic-buffer-cap {args.per_topic_buffer_cap} \\
    --global-buffer-cap {args.global_buffer_cap} \\
    --val-reservoir-size {args.val_reservoir_size} \\
    --shuffle-seed {args.shuffle_seed}
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
        ignore_patterns=[".state.json", ".val_reservoir.parquet", "*.tmp"],
    )
    print(f"Upload complete: https://huggingface.co/datasets/{repo_id}")


# -----------------------------------------------------------------------------
# Schema verification

def verify_schema(row, text_column, topic_column):
    """Print discovered schema; assert required columns; return whether topic column is present."""
    keys = list(row.keys())
    print(f"\nSource row keys ({len(keys)}): {keys}")
    print("Sample values:")
    for k in keys[:25]:
        v = row[k]
        if isinstance(v, str):
            sv = v[:80] + "..." if len(v) > 80 else v
            print(f"  {k}: {sv!r}")
        elif isinstance(v, list):
            preview = ""
            if v:
                first = str(v[0])
                preview = f" first={(first[:60] + '...') if len(first) > 60 else first!r}"
            print(f"  {k}: [list len={len(v)}]{preview}")
        else:
            print(f"  {k}: {v!r}"[:120])

    missing_required = [c for c in (text_column,) + REQUIRED_FILTER_COLUMNS if c not in row]
    if missing_required:
        raise SystemExit(
            f"\nFATAL: source row is missing required columns: {missing_required}\n"
            f"Available columns: {keys}\n"
            f"Re-run with --text-column NAME if the text column has a different name."
        )

    if topic_column not in row:
        print(f"\nWARNING: topic column '{topic_column}' not present in source row.")
        print("Falling back to no-topic-balance (single bucket; diversity reduced).\n")
        return False

    sample_text = row.get(text_column)
    if isinstance(sample_text, list):
        print(f"\nText column '{text_column}' is list-of-strings (per-page). "
              f"Pages will be joined with '\\n\\n'.")
    print()
    return True


# -----------------------------------------------------------------------------
# Main processing loop

def process(args, token):
    os.makedirs(args.output_dir, exist_ok=True)

    state = load_state(args.output_dir)
    if state is None:
        state = {
            "shard_index": 0,
            "rows_seen": 0,
            "rows_passed": 0,
            "total_chars": 0,
            "rejections": {},
            "pass_by_year_source": {},
            "topic_distribution_overall": {},
            "shards": [],
            "last_updated": None,
        }
    else:
        print(f"Resuming: shard_index={state['shard_index']}, "
              f"rows_seen={state['rows_seen']:,}, rows_passed={state['rows_passed']:,}")
        # Backfill keys for older state files
        state.setdefault("pass_by_year_source", {})
        state.setdefault("topic_distribution_overall", {})

    # Load val reservoir from sidecar (survives session restart)
    val_reservoir = load_val_reservoir(args.output_dir)
    if val_reservoir:
        print(f"Loaded {len(val_reservoir):,} rows from existing .val_reservoir.parquet")

    # Authenticate to HF — gated dataset requires explicit login, not just token=
    print("Authenticating to HuggingFace (gated dataset)...")
    huggingface_hub.login(token=token, add_to_git_credential=False)

    print(f"Loading streaming dataset: {SOURCE_DATASET} (split={SOURCE_SPLIT})")
    ds = load_dataset(SOURCE_DATASET, split=SOURCE_SPLIT, streaming=True)

    if state["rows_seen"] > 0:
        print(f"Skipping {state['rows_seen']:,} rows to resume...")
        ds = ds.skip(state["rows_seen"])

    # In-flight state
    schema_verified = False
    has_topic_column = not args.no_topic_balance
    shard_index = state["shard_index"]
    shard_docs = []
    shard_topics = []  # parallel to shard_docs (for per-shard topic_distribution)
    shard_chars = 0
    topic_deques: dict[str, deque] = defaultdict(deque)
    recent_yield_step: dict[str, int] = defaultdict(lambda: -1)
    current_step = 0
    run_rows_seen = 0  # rows pulled from source THIS RUN (since last flush)

    rng = random.Random(args.shuffle_seed)

    t_start = time.time()
    t_last_log = t_start

    def balanced_yield():
        """Yield one (text, topic) from the least-recently-yielded non-empty topic deque."""
        nonlocal current_step
        candidates = [t for t, d in topic_deques.items() if d]
        if not candidates:
            return None
        target = min(candidates, key=lambda t: recent_yield_step[t])
        d = topic_deques[target]
        idx = rng.randrange(len(d))
        d[idx], d[-1] = d[-1], d[idx]  # O(1) swap-and-pop
        item = d.pop()
        recent_yield_step[target] = current_step
        current_step += 1
        return item

    def flush_shard():
        nonlocal shard_index, shard_chars, run_rows_seen
        if not shard_docs:
            return
        filename, _ = write_shard(
            args.output_dir, shard_index, shard_docs, args.row_group_size
        )
        topic_counts = dict(Counter(shard_topics))
        record = {
            "index": shard_index,
            "filename": filename,
            "num_docs": len(shard_docs),
            "num_chars": shard_chars,
            "topic_distribution": topic_counts,
        }
        state["shards"].append(record)
        state["total_chars"] += shard_chars
        state["rows_seen"] += run_rows_seen
        state["shard_index"] = shard_index + 1
        state["last_updated"] = datetime.now(timezone.utc).isoformat()
        for t, c in topic_counts.items():
            state["topic_distribution_overall"][t] = state["topic_distribution_overall"].get(t, 0) + c
        save_state_atomic(args.output_dir, state)
        save_val_reservoir(args.output_dir, val_reservoir)
        top3 = sorted(topic_counts.items(), key=lambda x: -x[1])[:3]
        print(f"WROTE {filename} | docs={len(shard_docs):,} chars={shard_chars:,} "
              f"topics={len(topic_counts)} top3={top3}")
        shard_index += 1
        shard_docs.clear()
        shard_topics.clear()
        shard_chars = 0
        run_rows_seen = 0

    def maybe_flush():
        if shard_chars >= args.chars_per_shard:
            flush_shard()
            return True
        return False

    def add_to_shard(text, topic):
        nonlocal shard_chars
        shard_docs.append(text)
        shard_topics.append(topic)
        shard_chars += len(text)

    def _sigterm(signum, frame):
        print(f"\nSignal {signum}; exiting cleanly. State already on disk; "
              f"in-flight buffer ({len(shard_docs)} docs, "
              f"{sum(len(d) for d in topic_deques.values())} topic-deque docs) discarded.")
        sys.exit(0)
    signal.signal(signal.SIGTERM, _sigterm)

    try:
        for row in ds:
            run_rows_seen += 1

            if not schema_verified:
                has_topic_column = verify_schema(row, args.text_column, args.topic_column)
                if args.no_topic_balance:
                    has_topic_column = False
                schema_verified = True

            verdict, year_or_reason = classify_row(
                row, args.year_max, args.ocr_min, args.ocr_disagreement_max
            )

            if verdict == "reject":
                reason = year_or_reason
                state["rejections"][reason] = state["rejections"].get(reason, 0) + 1
            else:
                year_src = year_or_reason
                text = extract_text(row, args.text_column)
                if not text:
                    state["rejections"]["empty_text"] = state["rejections"].get("empty_text", 0) + 1
                else:
                    topic = (row.get(args.topic_column) if has_topic_column else None) or UNKNOWN_TOPIC
                    state["pass_by_year_source"][year_src] = state["pass_by_year_source"].get(year_src, 0) + 1
                    state["rows_passed"] += 1
                    n = state["rows_passed"]

                    # ----- Val reservoir (uniform sample over all passing rows) -----
                    K = args.val_reservoir_size
                    routed_to_training = True
                    if len(val_reservoir) < K:
                        val_reservoir.append((text, topic))
                        routed_to_training = False
                    else:
                        idx = rng.randint(0, n - 1)
                        if idx < K:
                            displaced = val_reservoir[idx]
                            val_reservoir[idx] = (text, topic)
                            text, topic = displaced  # use displaced for training

                    # ----- Route to training (topic-balanced or direct) -----
                    if routed_to_training:
                        if has_topic_column:
                            topic_deques[topic].append((text, topic))
                            # Drain via balanced rule when caps breached
                            while (len(topic_deques[topic]) > args.per_topic_buffer_cap
                                   or sum(len(d) for d in topic_deques.values()) > args.global_buffer_cap):
                                out = balanced_yield()
                                if out is None:
                                    break
                                t, top = out
                                add_to_shard(t, top)
                                maybe_flush()
                                if args.max_shards > 0 and shard_index >= args.max_shards:
                                    break
                        else:
                            add_to_shard(text, topic)
                            maybe_flush()

            # Periodic log
            now = time.time()
            if now - t_last_log > 15.0:
                running_rows_seen = state["rows_seen"] + run_rows_seen
                rate = run_rows_seen / max(1e-6, now - t_start)
                pr = 100.0 * state["rows_passed"] / max(1, running_rows_seen)
                buf_total = sum(len(d) for d in topic_deques.values())
                top3 = sorted([(t, len(d)) for t, d in topic_deques.items()], key=lambda x: -x[1])[:3]
                print(
                    f"[{now - t_start:6.0f}s] seen={running_rows_seen:,} "
                    f"pass={state['rows_passed']:,} ({pr:.2f}%) "
                    f"shard={shard_index} buf_chars={shard_chars:,} "
                    f"({100.0*shard_chars/args.chars_per_shard:.1f}%) "
                    f"topic_buf={buf_total} reservoir={len(val_reservoir)}/{args.val_reservoir_size} "
                    f"top3={top3} rate={rate:.1f} rows/s"
                )
                t_last_log = now

            if args.max_shards > 0 and shard_index >= args.max_shards:
                print(f"Reached --max-shards={args.max_shards}, stopping.")
                break
            if args.max_rows > 0 and (state["rows_seen"] + run_rows_seen) >= args.max_rows:
                print(f"Reached --max-rows={args.max_rows}, stopping.")
                break

    except KeyboardInterrupt:
        buf_total = sum(len(d) for d in topic_deques.values())
        print(f"\nKeyboardInterrupt: discarding {len(shard_docs)} in-flight shard docs + "
              f"{buf_total} topic-deque docs. Resume from state file.")
        # Note: val_reservoir snapshot WAS saved on last flush; the
        # post-last-flush rows that touched the reservoir will be re-tried on resume

    # End-of-stream: drain remaining topic deques via the balanced rule
    if has_topic_column and any(topic_deques.values()):
        remaining = sum(len(d) for d in topic_deques.values())
        print(f"Draining {remaining:,} remaining rows from topic deques (end of stream)...")
        while any(topic_deques.values()):
            out = balanced_yield()
            if out is None:
                break
            t, top = out
            add_to_shard(t, top)
            maybe_flush()
            if args.max_shards > 0 and shard_index >= args.max_shards:
                break

    # Final training shard flush
    if shard_docs:
        flush_shard()

    # ---- Write val reservoir as the FINAL shard (last lexicographic = val) ----
    if val_reservoir:
        val_docs = [t for t, _ in val_reservoir]
        val_topics = [top for _, top in val_reservoir]
        val_chars = sum(len(t) for t in val_docs)
        filename, _ = write_shard(args.output_dir, state["shard_index"], val_docs, args.row_group_size)
        topic_counts = dict(Counter(val_topics))
        record = {
            "index": state["shard_index"],
            "filename": filename,
            "num_docs": len(val_docs),
            "num_chars": val_chars,
            "topic_distribution": topic_counts,
            "is_val": True,
        }
        state["shards"].append(record)
        state["total_chars"] += val_chars
        state["shard_index"] += 1
        state["last_updated"] = datetime.now(timezone.utc).isoformat()
        for t, c in topic_counts.items():
            state["topic_distribution_overall"][t] = state["topic_distribution_overall"].get(t, 0) + c
        save_state_atomic(args.output_dir, state)
        print(f"WROTE VAL {filename} | docs={len(val_docs):,} chars={val_chars:,} "
              f"topics={len(topic_counts)}")

    # README + manifest
    totals = {
        "rows_seen": state["rows_seen"],
        "rows_passed": state["rows_passed"],
        "total_chars": state["total_chars"],
        "num_shards": len(state["shards"]),
        "rejections": state["rejections"],
        "pass_by_year_source": state["pass_by_year_source"],
        "topic_distribution_overall": state["topic_distribution_overall"],
    }
    update_manifest(args.output_dir, args, state["shards"], totals)
    write_readme(args.output_dir, args, totals, state["shards"])

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
                   help="Directory to write shards to (e.g. $NANOCHAT_BASE_DIR/base_data_books)")
    # Filter args
    p.add_argument("--year-max", type=int, default=1930,
                   help="Exclusive upper bound on parsed year (default: 1930)")
    p.add_argument("--ocr-min", type=float, default=85.0,
                   help="Exclusive lower bound on each OCR score (default: 85)")
    p.add_argument("--ocr-disagreement-max", type=float, default=15.0,
                   help="Exclusive upper bound on |src - gen| OCR disagreement (default: 15)")
    # Column overrides
    p.add_argument("--text-column", type=str, default="text_by_page_gen",
                   help="Source text column (default: text_by_page_gen — authors' cleaned per-page text, "
                        "joined with '\\n\\n')")
    p.add_argument("--topic-column", type=str, default="topic_or_subject_gen",
                   help="LCC topic column for Mechanism 1 (default: topic_or_subject_gen)")
    # Shard layout
    p.add_argument("--chars-per-shard", type=int, default=250_000_000,
                   help="Target characters per shard before flush (default: 250M, ~100MB compressed)")
    p.add_argument("--row-group-size", type=int, default=64,
                   help="Parquet row group size (default: 64; books avg ~1M chars/row so smaller "
                        "row groups keep dataloader peak memory bounded)")
    # Diversity
    p.add_argument("--per-topic-buffer-cap", type=int, default=1024,
                   help="Max books per topic deque before forced balanced drain (default: 1024)")
    p.add_argument("--global-buffer-cap", type=int, default=8192,
                   help="Total across all topic deques before forced drain (default: 8192)")
    p.add_argument("--val-reservoir-size", type=int, default=1000,
                   help="Books reserved for val via reservoir sampling, written as last shard "
                        "(default: 1000)")
    p.add_argument("--shuffle-seed", type=int, default=42,
                   help="RNG seed for reservoir sampling and within-topic shuffle (default: 42)")
    p.add_argument("--no-topic-balance", action="store_true",
                   help="Disable Mechanism 1 (topic deques); fall back to direct linear write")
    # Limits (for smoke tests)
    p.add_argument("--max-shards", type=int, default=-1,
                   help="Stop after writing this many shards (-1 = unlimited)")
    p.add_argument("--max-rows", type=int, default=-1,
                   help="Stop after seeing this many source rows (-1 = unlimited)")
    # Upload
    p.add_argument("--upload", action="store_true",
                   help="Upload to HF after processing completes")
    p.add_argument("--upload-only", action="store_true",
                   help="Skip processing; only upload an already-built output dir")
    p.add_argument("--repo-id", type=str, default="jbduran/think-institutional-books",
                   help="HF dataset repo id (will be created private if missing)")
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

    if args.upload:
        upload_to_hf(args.output_dir, args.repo_id, token)


if __name__ == "__main__":
    main()
