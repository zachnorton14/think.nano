"""Stage 0.5: footer / boilerplate line stripping.

Reads the clean corpus (STRIP_SRC_REPO), removes footer lines from every document
(see footer_lib.strip_footers), and writes stripped shards under STRIP_PREFIX/ in
DST_REPO -- same shard basenames. The anachronism filter (Stage 3) then reads that
stripped layer. Resumable per shard; prints a per-shard ETA.

Per shard it uploads:
  stripped/shard_XXXXX.parquet   -- the footer-stripped text (one 'text' column)
  strip_stats/shard_XXXXX.json   -- counts + removed_by_pattern + flagged docs
  strip_samples/shard_XXXXX.jsonl-- a sample of removed footer lines, for auditing

Run:            python scripts/strip_footers.py
First-shard dry-run:  DRY_RUN_LIMIT=1 python scripts/strip_footers.py
"""
import json
import time
from collections import defaultdict
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import CommitOperationAdd

import config
from footer_lib import strip_footers
from common import (
    api,
    destination_shards,
    download_source_shard,
    ensure_dst_repo,
    output_path_for_source,
    source_shards,
)

SAMPLE_LINES_PER_SHARD = 400   # cap on removed-line samples written per shard


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
    output_name = output_path_for_source(path_in_repo)      # shard_XXXXX.parquet
    stem = Path(output_name).stem
    local_source = download_source_shard(path_in_repo, repo_id=config.STRIP_SRC_REPO)
    local_out = config.STRIP_OUT_DIR / output_name
    local_stats = config.STRIP_OUT_DIR / f"{stem}.json"
    local_samples = config.STRIP_OUT_DIR / f"{stem}.jsonl"

    stats = {
        "source_shard": path_in_repo,
        "output_shard": f"{config.STRIP_PREFIX}/{output_name}",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_docs": 0,
        "n_docs_changed": 0,
        "n_docs_flagged_unstripped": 0,
        "n_lines_removed": 0,
        "chars_in": 0, "chars_out": 0,
        "removed_by_pattern": defaultdict(int),
    }

    out_texts, samples = [], []
    pf = pq.ParquetFile(local_source)
    doc_idx = -1
    for rg_idx in range(pf.num_row_groups):
        table = pf.read_row_group(rg_idx, columns=["text"])
        for text in table.column("text").to_pylist():
            doc_idx += 1
            stats["n_docs"] += 1
            stats["chars_in"] += len(text) if isinstance(text, str) else 0
            clean, removed, flagged = strip_footers(text)
            if flagged:
                stats["n_docs_flagged_unstripped"] += 1
            for name, line in removed:
                stats["removed_by_pattern"][name] += 1
            if removed and not flagged:
                stats["n_docs_changed"] += 1
                stats["n_lines_removed"] += len(removed)
                if len(samples) < SAMPLE_LINES_PER_SHARD:
                    for name, line in removed[:20]:
                        samples.append({"doc_idx": doc_idx, "pattern": name, "line": line})
            out_texts.append(clean)   # flagged docs keep original text (clean == text)
            stats["chars_out"] += len(clean) if isinstance(clean, str) else 0

    stats["removed_by_pattern"] = dict(stats["removed_by_pattern"])
    stats["chars_removed_pct"] = (
        100.0 * (stats["chars_in"] - stats["chars_out"]) / max(stats["chars_in"], 1)
    )
    stats["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    write_parquet_texts(out_texts, local_out)
    with open(local_stats, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, sort_keys=True)
    with open(local_samples, "w", encoding="utf-8") as f:
        for rec in samples:
            f.write(json.dumps(rec) + "\n")

    api.create_commit(
        repo_id=config.DST_REPO, repo_type="dataset",
        operations=[
            CommitOperationAdd(f"{config.STRIP_PREFIX}/{output_name}", str(local_out)),
            CommitOperationAdd(f"strip_stats/{stem}.json", str(local_stats)),
            CommitOperationAdd(f"strip_samples/{stem}.jsonl", str(local_samples)),
        ],
        commit_message=f"strip footers {output_name} ({stats['n_lines_removed']} lines)",
    )
    return stats


def main():
    ensure_dst_repo()
    config.ensure_dirs()

    all_source = source_shards(repo_id=config.STRIP_SRC_REPO, root_only=True)
    done = destination_shards(prefix=config.STRIP_PREFIX)
    done_names = {Path(p).name for p in done}
    todo = [s for s in all_source if output_path_for_source(s) not in done_names]
    print(f"Footer-strip source: {config.STRIP_SRC_REPO} -> {config.DST_REPO}/{config.STRIP_PREFIX}/")
    print(f"Source shards: {len(all_source):,} | already stripped: {len(all_source) - len(todo):,} | remaining: {len(todo):,}")

    if config.DRY_RUN_LIMIT:
        todo = todo[:config.DRY_RUN_LIMIT]
        print(f"DRY_RUN_LIMIT={config.DRY_RUN_LIMIT}: stripping only {len(todo)} shard(s) this run. "
              f"Inspect strip_samples/ on HF before running the rest.")

    t0 = time.time()
    n_total = len(todo)
    for i, shard in enumerate(todo, start=1):
        st = process_shard(shard)
        elapsed = time.time() - t0
        avg = elapsed / i
        eta = avg * (n_total - i)
        top = sorted(st["removed_by_pattern"].items(), key=lambda x: -x[1])[:5]
        print(
            f"[{i}/{n_total}] {st['output_shard']}: docs {st['n_docs']:,} "
            f"changed={st['n_docs_changed']:,} flagged={st['n_docs_flagged_unstripped']:,} "
            f"lines_removed={st['n_lines_removed']:,} chars-{st['chars_removed_pct']:.2f}% | "
            f"elapsed {fmt_secs(elapsed)} | avg {avg:.1f}s/shard | "
            f"ETA ~{fmt_secs(eta)} for {n_total - i} left | top={top}"
        )

    print(f"\nThis run stripped {len(todo):,} shard(s) in {fmt_secs(time.time() - t0)}.")
    if config.DRY_RUN_LIMIT and (len(all_source) - len(done_names)) > len(todo):
        print("Dry run done. Inspect strip_samples/shard_00000.jsonl on HF, then unset "
              "DRY_RUN_LIMIT and re-run to strip the rest (completed shards are skipped).")


if __name__ == "__main__":
    main()
