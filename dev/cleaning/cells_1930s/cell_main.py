# ---------------------------------------------------------------------------
# MAIN RESUMABLE SHARD LOOP
#
# For each source shard: download -> scan every document -> keep or drop whole
# docs -> write same-named output shard + stats + per-shard hit log, all in one
# commit. Resumes by skipping shards already present in the destination repo.
# Prints a per-item ETA using a running average of seconds/shard.
# ---------------------------------------------------------------------------


def source_shards():
    files = list_repo_files_safe(SRC_REPO)
    shards = sorted([p for p in files if re.match(r"(^|.*/)shard_\d+\.parquet$", p)])
    if not shards:
        shards = sorted([p for p in files if p.endswith(".parquet")])
    print(f"Found {len(shards):,} source parquet shards in {SRC_REPO}.")
    return shards


def destination_shards():
    files = list_repo_files_safe(DST_REPO)
    return set(p for p in files if re.match(r"(^|.*/)shard_\d+\.parquet$", p))


def download_source_shard(path_in_repo):
    return hf_hub_download(
        repo_id=SRC_REPO,
        repo_type="dataset",
        filename=path_in_repo,
        token=HF_TOKEN,
        local_dir=SRC_CACHE,
    )


def output_path_for_source(path_in_repo):
    return Path(path_in_repo).name


def write_parquet_texts(texts, local_out):
    table = pa.table({"text": texts})
    pq.write_table(
        table,
        local_out,
        row_group_size=ROW_GROUP_SIZE,
        compression=COMPRESSION,
        compression_level=COMPRESSION_LEVEL,
    )


def fmt_secs(s):
    m, s = divmod(int(s), 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def process_shard(path_in_repo):
    output_name = output_path_for_source(path_in_repo)
    stem = Path(output_name).stem
    local_source = download_source_shard(path_in_repo)
    local_out = OUT_DIR / output_name
    local_stats = OUT_DIR / f"{stem}.json"
    local_hits = OUT_DIR / f"{stem}.jsonl"

    stats = {
        "source_shard": path_in_repo,
        "output_shard": output_name,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_input": 0,
        "n_kept": 0,
        "n_removed": 0,
        "removed_by_term": defaultdict(int),
        "removed_by_kind": defaultdict(int),
        "chars_in": 0,
        "chars_kept": 0,
    }

    kept_texts = []
    hit_records = []
    pf = pq.ParquetFile(local_source)
    doc_idx = -1
    for rg_idx in range(pf.num_row_groups):
        table = pf.read_row_group(rg_idx, columns=["text"])
        for text in table.column("text").to_pylist():
            doc_idx += 1
            stats["n_input"] += 1
            stats["chars_in"] += len(text) if isinstance(text, str) else 0
            terms, kinds = scan_text(text)
            if should_drop(terms):
                stats["n_removed"] += 1
                for t in terms:
                    stats["removed_by_term"][t] += 1
                for k in kinds:
                    stats["removed_by_kind"][k] += 1
                # Per-shard hit log: which document, which terms, which kinds.
                hit_records.append({"doc_idx": doc_idx, "terms": terms, "kinds": kinds})
                continue
            kept_texts.append(text)  # unchanged -- whole book preserved
            stats["n_kept"] += 1
            stats["chars_kept"] += len(text) if isinstance(text, str) else 0

    stats["removed_by_term"] = dict(stats["removed_by_term"])
    stats["removed_by_kind"] = dict(stats["removed_by_kind"])
    stats["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    write_parquet_texts(kept_texts, local_out)
    with open(local_stats, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, sort_keys=True)
    with open(local_hits, "w", encoding="utf-8") as f:
        for rec in hit_records:
            f.write(json.dumps(rec) + "\n")

    api.create_commit(
        repo_id=DST_REPO,
        repo_type="dataset",
        operations=[
            CommitOperationAdd(path_in_repo=output_name, path_or_fileobj=str(local_out)),
            CommitOperationAdd(path_in_repo=f"stats/{stem}.json", path_or_fileobj=str(local_stats)),
            CommitOperationAdd(path_in_repo=f"hits/{stem}.jsonl", path_or_fileobj=str(local_hits)),
        ],
        commit_message=f"filter {output_name} ({stats['n_removed']} dropped)",
    )
    return stats


SOURCE_SHARDS = source_shards()
done = destination_shards()
todo = [s for s in SOURCE_SHARDS if output_path_for_source(s) not in done]
print(f"Already completed: {len(SOURCE_SHARDS) - len(todo):,}/{len(SOURCE_SHARDS):,}")
print(f"Remaining shards:  {len(todo):,}")

# --- OPTIONAL DRY RUN --------------------------------------------------------
# Strongly recommended on the first run: process ONE shard, then inspect
# hits/shard_00000.jsonl on HF to confirm the hits are real anachronisms and
# not false positives, before committing to all 329 shards. Set to a number to
# cap this run; set to None to process everything remaining.
DRY_RUN_LIMIT = 1
if DRY_RUN_LIMIT is not None:
    todo = todo[:DRY_RUN_LIMIT]
    print(f"DRY_RUN_LIMIT set: processing only {len(todo)} shard(s) this run. "
          f"Set DRY_RUN_LIMIT = None to process everything.")
# ----------------------------------------------------------------------------

all_stats = []
t0 = time.time()
n_total = len(todo)
for i, shard in enumerate(tqdm(todo, desc="filtering shards"), start=1):
    try:
        st = process_shard(shard)
        all_stats.append(st)
        removed_pct = 100.0 * st["n_removed"] / max(st["n_input"], 1)
        elapsed = time.time() - t0
        avg = elapsed / i
        eta = avg * (n_total - i)
        top_terms = sorted(st["removed_by_term"].items(), key=lambda x: -x[1])[:5]
        print(
            f"{st['output_shard']}: kept {st['n_kept']:,}/{st['n_input']:,} "
            f"removed={st['n_removed']:,} ({removed_pct:.2f}%) | "
            f"elapsed {fmt_secs(elapsed)} | avg {avg:.1f}s/shard | "
            f"ETA ~{fmt_secs(eta)} for {n_total - i} left | "
            f"top={top_terms}"
        )
    except Exception as exc:
        print(f"ERROR while processing {shard}: {exc}")
        raise

elapsed = time.time() - t0
print(f"\nThis run processed {len(all_stats):,} shard(s) in {fmt_secs(elapsed)}.")
if DRY_RUN_LIMIT is not None and (len(SOURCE_SHARDS) - len(done)) > len(all_stats):
    print("Dry run complete. Inspect hits/ on HF, then set DRY_RUN_LIMIT = None "
          "and re-run this cell to process the rest (already-done shards are skipped).")
