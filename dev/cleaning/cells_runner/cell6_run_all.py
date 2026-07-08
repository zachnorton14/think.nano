# === Stage 3 (full run): process all remaining shards =======================
# After you've inspected the dry-run hit log and are happy, run this to process
# the rest. DRY_RUN_LIMIT=0 means "all remaining"; completed shards are skipped,
# so this is safe to re-run after any Colab disconnect until everything is done.
# Reads the footer-stripped layer (same as the dry run).
!cd "{CLONE_DIR}" && SRC_REPO="{DST_REPO}" SRC_PREFIX=stripped DRY_RUN_LIMIT=0 python scripts/run_filter.py
