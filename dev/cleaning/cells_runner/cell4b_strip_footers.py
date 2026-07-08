# === Stage 0.5: strip footers / boilerplate (runs BEFORE the filter) ========
# Reads the clean corpus, removes footer lines (URLs, "printed in USA", "all rights
# reserved", photocopy / print-on-demand colophons, ISBN lines, bare page numbers,
# library stamps) from each document, and writes the stripped corpus to `stripped/`
# in the destination repo. Whole books are kept -- only footer lines are removed.
#
# DRY RUN FIRST: this strips ONE shard (DRY_RUN_LIMIT=1). Then open
# strip_samples/shard_00000.jsonl on HF and confirm only real footer lines were
# removed (not book text). When happy, set DRY_RUN_LIMIT=0 below and re-run to
# strip the rest (already-stripped shards are skipped).
!cd "{CLONE_DIR}" && DRY_RUN_LIMIT=1 python scripts/strip_footers.py
