"""Stage 0: guarded clean command -- start the destination dataset from scratch.

Deletes generated files from the destination repo. Guarded: does nothing unless
CONFIRM_WIPE=1. Flags:
  WIPE_BANNED_LIST=1  also delete _banned/ (the tiered list)
  WIPE_STRIPPED=1     also delete the footer-stripped layer (stripped/, strip_*)

By default a wipe removes the FINAL filter outputs (shards/stats/hits/report) but
KEEPS the stripped layer, so you can re-run just the filter without re-stripping.

Run:  CONFIRM_WIPE=1 python scripts/wipe.py
      CONFIRM_WIPE=1 WIPE_STRIPPED=1 WIPE_BANNED_LIST=1 python scripts/wipe.py
"""
import os
import re

from huggingface_hub import CommitOperationDelete

import config
from common import api, ensure_dst_repo, list_repo_files_safe

CONFIRM_WIPE = os.environ.get("CONFIRM_WIPE", "0") == "1"
WIPE_BANNED_LIST = os.environ.get("WIPE_BANNED_LIST", "0") == "1"
WIPE_STRIPPED = os.environ.get("WIPE_STRIPPED", "0") == "1"


def main():
    ensure_dst_repo()
    if not CONFIRM_WIPE:
        print("CONFIRM_WIPE not set; leaving destination repo untouched.")
        print("Re-run with  CONFIRM_WIPE=1 python scripts/wipe.py  to delete generated files.")
        return

    strip_pref = config.STRIP_PREFIX.rstrip("/") + "/"
    files = list_repo_files_safe(config.DST_REPO)
    delete_paths = []
    for path in files:
        # Stripped layer + its sidecars are gated behind WIPE_STRIPPED.
        is_stripped = (
            path.startswith(strip_pref)
            or path.startswith("strip_stats/")
            or path.startswith("strip_samples/")
        )
        if is_stripped:
            if WIPE_STRIPPED:
                delete_paths.append(path)
            continue
        # Final filter outputs (at repo root).
        is_shard = re.match(r"^shard_\d+\.parquet$", path) is not None
        is_stat = re.match(r"^stats/shard_\d+\.json$", path) is not None
        is_hits = re.match(r"^hits/shard_\d+\.jsonl$", path) is not None
        is_report = path == "cleaning_report_1930s.json"
        is_banned = path.startswith("_banned/") if WIPE_BANNED_LIST else False
        if is_shard or is_stat or is_hits or is_report or is_banned:
            delete_paths.append(path)

    if not delete_paths:
        print("No generated files found to delete.")
        return

    print(f"Deleting {len(delete_paths):,} generated files from {config.DST_REPO}...")
    for start in range(0, len(delete_paths), 100):
        batch = delete_paths[start:start + 100]
        api.create_commit(
            repo_id=config.DST_REPO, repo_type="dataset",
            operations=[CommitOperationDelete(path_in_repo=p) for p in batch],
            commit_message=f"wipe generated 1930s outputs {start // 100 + 1}",
        )
        print(f"  deleted {start + len(batch):,}/{len(delete_paths):,}")


if __name__ == "__main__":
    main()
