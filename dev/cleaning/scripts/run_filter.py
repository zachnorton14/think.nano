"""Stage 3: main resumable shard loop.

Downloads (or builds) the banned list, compiles the fast matcher, then for each
source shard: scans every whole-book row, drops docs with anachronism hits, and
writes a same-named output shard + per-shard stats + a per-shard hit log, all in
one commit. Resumes by skipping shards already present in the destination repo.
Prints a per-shard ETA from a running average.

Run:            python scripts/run_filter.py
First-shard dry-run:  DRY_RUN_LIMIT=1 python scripts/run_filter.py
"""
import json
import time
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import CommitOperationAdd

import config
import filter_lib
from build_list import load_or_build
from common import (
    BatchCommitter,
    destination_shards,
    download_source_shard,
    ensure_dst_repo,
    output_path_for_source,
    source_shards,
)


def write_parquet_texts(texts, local_out):
    table = pa.table({"text": texts})
    pq.write_table(
        table, local_out,
        row_group_size=config.ROW_GROUP_SIZE,
        compression=config.COMPRESSION,
        compression_level=config.COMPRESSION_LEVEL,
    )


def fmt_secs(s):
    m, s = divmod(int(s), 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def process_shard(path_in_repo):
    output_name = output_path_for_source(path_in_repo)
    stem = Path(output_name).stem
    local_source = download_source_shard(path_in_repo)
    local_out = config.OUT_DIR / output_name
    local_stats = config.OUT_DIR / f"{stem}.json"
    local_hits = config.OUT_DIR / f"{stem}.jsonl"

    stats = {
        "source_shard": path_in_repo,
        "output_shard": output_name,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_input": 0, "n_kept": 0, "n_removed": 0,
        "removed_by_term": defaultdict(int),   # terms that caused drops
        "removed_by_reason": defaultdict(int),  # tier1 vs corroborated_tier2
        "boilerplate_hits": defaultdict(int),   # strip-only signals seen (kept docs)
        "chars_in": 0, "chars_kept": 0,
    }

    kept_texts, hit_records = [], []
    pf = pq.ParquetFile(local_source)
    doc_idx = -1
    for rg_idx in range(pf.num_row_groups):
        table = pf.read_row_group(rg_idx, columns=["text"])
        for text in table.column("text").to_pylist():
            doc_idx += 1
            stats["n_input"] += 1
            stats["chars_in"] += len(text) if isinstance(text, str) else 0
            terms, kinds = filter_lib.scan_text(text)
            drop, reason, by_tier = filter_lib.decide_drop(terms)
            if drop:
                stats["n_removed"] += 1
                stats["removed_by_reason"][reason] += 1
                # Only the tiered signals that actually justified the drop.
                for t in by_tier[1] + by_tier[2] + by_tier[3]:
                    stats["removed_by_term"][t] += 1
                hit_records.append({
                    "doc_idx": doc_idx, "reason": reason,
                    "tier1": by_tier[1], "tier2": by_tier[2],
                    "tier3": by_tier[3], "strip": by_tier["strip"],
                })
                continue
            # Kept doc: still note any boilerplate/strip-only signals for auditing.
            for t in by_tier["strip"]:
                stats["boilerplate_hits"][t] += 1
            kept_texts.append(text)  # unchanged -- whole book preserved
            stats["n_kept"] += 1
            stats["chars_kept"] += len(text) if isinstance(text, str) else 0

    stats["removed_by_term"] = dict(stats["removed_by_term"])
    stats["removed_by_reason"] = dict(stats["removed_by_reason"])
    stats["boilerplate_hits"] = dict(stats["boilerplate_hits"])
    stats["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    write_parquet_texts(kept_texts, local_out)
    with open(local_stats, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, sort_keys=True)
    with open(local_hits, "w", encoding="utf-8") as f:
        for rec in hit_records:
            f.write(json.dumps(rec) + "\n")

    # Return the upload operations; the caller batches them into one commit.
    ops = [
        CommitOperationAdd(output_name, str(local_out)),
        CommitOperationAdd(f"stats/{stem}.json", str(local_stats)),
        CommitOperationAdd(f"hits/{stem}.jsonl", str(local_hits)),
    ]
    return stats, ops


def main():
    ensure_dst_repo()
    config.ensure_dirs()

    banned_terms, meta, tiers = load_or_build()
    filter_lib.init_matcher(banned_terms, tiers)
    tc = (meta or {}).get("tier_counts", {})
    print(f"Matcher ready: {len(banned_terms):,} banned terms "
          f"(T1={tc.get('tier1', 0)} T2={tc.get('tier2', 0)} T3={tc.get('tier3', 0)} "
          f"strip={tc.get('strip', 0)}), {len(filter_lib.FORMAT_RES)} format tells. "
          f"Drop rule: 1x T1 OR >=2 T2/T3 with >=1 T2. "
          f"Scan window: head={config.SCAN_CHARS or 'ALL'} tail={config.SCAN_TAIL_CHARS}.")

    # Read shards from SRC_REPO/SRC_PREFIX -- point these at the stripped layer:
    #   SRC_REPO=<dst repo>  SRC_PREFIX=stripped
    all_source = source_shards(prefix=config.SRC_PREFIX)
    done = destination_shards(root_only=True)   # final shards live at repo root only
    done_names = {Path(p).name for p in done}
    todo = [s for s in all_source if output_path_for_source(s) not in done_names]
    src_desc = f"{config.SRC_REPO}" + (f"/{config.SRC_PREFIX}/" if config.SRC_PREFIX else "")
    print(f"Filter input: {src_desc}")
    print(f"Source shards: {len(all_source):,} | already done: {len(all_source) - len(todo):,} | remaining: {len(todo):,}")

    if config.DRY_RUN_LIMIT:
        todo = todo[:config.DRY_RUN_LIMIT]
        print(f"DRY_RUN_LIMIT={config.DRY_RUN_LIMIT}: processing only {len(todo)} shard(s) this run.")

    committer = BatchCommitter(
        repo_id=config.DST_REPO, batch_size=config.BATCH_SIZE,
        message_prefix="filter",
    )
    print(f"Batching uploads: {config.BATCH_SIZE} shard(s) per commit.")

    t0 = time.time()
    n_total = len(todo)
    for i, shard in enumerate(todo, start=1):
        st, ops = process_shard(shard)
        committed = committer.add(ops, label=st["output_shard"])
        removed_pct = 100.0 * st["n_removed"] / max(st["n_input"], 1)
        elapsed = time.time() - t0
        avg = elapsed / i
        eta = avg * (n_total - i)
        top = sorted(st["removed_by_term"].items(), key=lambda x: -x[1])[:5]
        flush_note = f" [committed batch #{committer.n_commits}]" if committed else f" [buffered {committer.pending}]"
        print(
            f"[{i}/{n_total}] {st['output_shard']}: kept {st['n_kept']:,}/{st['n_input']:,} "
            f"removed={st['n_removed']:,} ({removed_pct:.2f}%) | "
            f"elapsed {fmt_secs(elapsed)} | avg {avg:.1f}s/shard | "
            f"ETA ~{fmt_secs(eta)} for {n_total - i} left | top={top}{flush_note}"
        )

    committer.flush()   # push the final partial batch
    print(f"\nThis run processed {len(todo):,} shard(s) in {fmt_secs(time.time() - t0)} "
          f"({committer.n_commits} commit(s)).")
    if config.DRY_RUN_LIMIT and (len(all_source) - len(done)) > len(todo):
        print("Dry run complete. Inspect hits/ on HF, then unset DRY_RUN_LIMIT and re-run "
              "to process the rest (completed shards are skipped).")


if __name__ == "__main__":
    main()
