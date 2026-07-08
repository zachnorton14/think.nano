# === Stage 0.5 (full run): strip footers from all remaining shards ==========
# After you've inspected the dry-run strip samples and are happy, run this to
# strip the rest of the corpus. Already-stripped shards are skipped, so it's safe
# to re-run after any Colab disconnect until the whole corpus is stripped. Only
# then move on to the anachronism filter (Stage 3), which reads `stripped/`.
!cd "{CLONE_DIR}" && DRY_RUN_LIMIT=0 python scripts/strip_footers.py
