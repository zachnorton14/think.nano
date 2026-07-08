def process_one_text(text):
    cleaned, reason = structural_clean(text)
    if cleaned is None:
        return None, reason, None, len(text) if isinstance(text, str) else 0, 0

    mean_prior = doc_mean_log_prior(cleaned, LOG_PRIORS)
    if mean_prior is None:
        return None, "empty_tokenization", None, len(text), len(cleaned)
    if mean_prior < PRIOR_LOW:
        return None, "prior_low", mean_prior, len(text), len(cleaned)
    if mean_prior > PRIOR_HIGH:
        return None, "prior_high", mean_prior, len(text), len(cleaned)
    return cleaned, "ok", mean_prior, len(text), len(cleaned)


def write_parquet_texts(texts, local_out):
    table = pa.table({"text": texts})
    pq.write_table(
        table,
        local_out,
        row_group_size=ROW_GROUP_SIZE,
        compression=COMPRESSION,
        compression_level=COMPRESSION_LEVEL,
    )


def process_shard(path_in_repo):
    output_name = output_path_for_source(path_in_repo)
    local_source = download_source_shard(path_in_repo)
    local_out = OUT_DIR / output_name
    local_stats = OUT_DIR / f"{Path(output_name).stem}.json"

    stats = {
        "source_shard": path_in_repo,
        "output_shard": output_name,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_input": 0,
        "n_kept": 0,
        "n_removed": 0,
        "removed_by_reason": defaultdict(int),
        "chars_raw": 0,
        "chars_after_clean_before_prior": 0,
        "chars_kept": 0,
        "mean_prior_kept_sum": 0.0,
    }

    kept_texts = []
    pf = pq.ParquetFile(local_source)
    for rg_idx in range(pf.num_row_groups):
        table = pf.read_row_group(rg_idx, columns=["text"])
        for text in table.column("text").to_pylist():
            stats["n_input"] += 1
            cleaned, reason, mean_prior, raw_chars, clean_chars = process_one_text(text)
            stats["chars_raw"] += raw_chars
            stats["chars_after_clean_before_prior"] += clean_chars
            if cleaned is None:
                stats["n_removed"] += 1
                stats["removed_by_reason"][reason] += 1
                continue
            kept_texts.append(cleaned)
            stats["n_kept"] += 1
            stats["chars_kept"] += len(cleaned)
            stats["mean_prior_kept_sum"] += float(mean_prior)

    stats["removed_by_reason"] = dict(stats["removed_by_reason"])
    stats["mean_prior_kept"] = (
        stats["mean_prior_kept_sum"] / stats["n_kept"] if stats["n_kept"] else None
    )
    del stats["mean_prior_kept_sum"]
    stats["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    write_parquet_texts(kept_texts, local_out)
    with open(local_stats, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, sort_keys=True)

    api.create_commit(
        repo_id=DST_REPO,
        repo_type="dataset",
        operations=[
            CommitOperationAdd(path_in_repo=output_name, path_or_fileobj=str(local_out)),
            CommitOperationAdd(path_in_repo=f"stats/{Path(output_name).stem}.json", path_or_fileobj=str(local_stats)),
        ],
        commit_message=f"clean {output_name}",
    )
    return stats


done = destination_shards()
todo = [s for s in SOURCE_SHARDS if output_path_for_source(s) not in done]
print(f"Already completed: {len(SOURCE_SHARDS) - len(todo):,}/{len(SOURCE_SHARDS):,}")
print(f"Remaining shards:   {len(todo):,}")

all_stats = []
t0 = time.time()
for shard in tqdm(todo, desc="cleaning shards"):
    try:
        st = process_shard(shard)
        all_stats.append(st)
        removed_pct = 100.0 * st["n_removed"] / max(st["n_input"], 1)
        print(
            f"{st['output_shard']}: kept {st['n_kept']:,}/{st['n_input']:,} "
            f"removed={removed_pct:.2f}% reasons={st['removed_by_reason']}"
        )
    except Exception as exc:
        print(f"ERROR while processing {shard}: {exc}")
        raise

elapsed = time.time() - t0
print(f"Stage 2 complete for this run in {elapsed / 3600:.2f} h.")
