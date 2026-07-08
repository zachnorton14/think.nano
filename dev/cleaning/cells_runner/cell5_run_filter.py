# === Stage 3: main resumable shard loop =====================================
# Reads the FOOTER-STRIPPED layer (stripped/) produced by Stage 0.5 -- so the
# anachronism filter runs on clean text. (SRC_REPO=<dst repo>, SRC_PREFIX=stripped.)
#
# DRY RUN FIRST. This runs ONE shard (DRY_RUN_LIMIT=1), then stop and inspect
# hits/shard_00000.jsonl on HF to confirm the dropped docs are real anachronisms
# (not false positives). The loop skips shards already present in the destination,
# so it resumes automatically after a disconnect.
!cd "{CLONE_DIR}" && SRC_REPO="{DST_REPO}" SRC_PREFIX=stripped DRY_RUN_LIMIT=1 python scripts/run_filter.py
