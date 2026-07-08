def list_repo_files_safe(repo_id):
    try:
        return api.list_repo_files(repo_id=repo_id, repo_type="dataset")
    except Exception as exc:
        print(f"Could not list {repo_id}: {exc}")
        return []


def wipe_destination_shards(confirm=False, wipe_banned=False):
    """Delete generated shard/stat/hit/report files from the destination repo.

    Guarded by CONFIRM_WIPE. This is the requested 'start from scratch' command.
    """
    if not confirm:
        print("CONFIRM_WIPE is False; leaving destination repo untouched.")
        print("Set CONFIRM_WIPE = True and re-run this cell to delete generated files.")
        return

    files = list_repo_files_safe(DST_REPO)
    delete_paths = []
    for path in files:
        is_shard = re.match(r"(^|.*/)shard_\d+\.parquet$", path) is not None
        is_stat = re.match(r"(^|.*/)stats/shard_\d+\.json$", path) is not None
        is_hits = re.match(r"(^|.*/)hits/shard_\d+\.jsonl$", path) is not None
        is_report = path == "cleaning_report_1930s.json"
        is_banned = path.startswith("_banned/") if wipe_banned else False
        if is_shard or is_stat or is_hits or is_report or is_banned:
            delete_paths.append(path)

    if not delete_paths:
        print("No generated shard/stat/hit/report files found to delete.")
        return

    print(f"Deleting {len(delete_paths):,} generated files from {DST_REPO}...")
    for start in range(0, len(delete_paths), 100):
        batch = delete_paths[start:start + 100]
        api.create_commit(
            repo_id=DST_REPO,
            repo_type="dataset",
            operations=[CommitOperationDelete(path_in_repo=p) for p in batch],
            commit_message=f"wipe generated 1930s outputs {start // 100 + 1}",
        )
        print(f"  deleted {start + len(batch):,}/{len(delete_paths):,}")


wipe_destination_shards(confirm=CONFIRM_WIPE, wipe_banned=WIPE_BANNED_LIST)
