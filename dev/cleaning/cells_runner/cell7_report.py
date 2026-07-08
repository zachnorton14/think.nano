# === Stage 4: aggregate report + README =====================================
# Sums all per-shard stats, ranks which banned terms actually fired, and writes
# cleaning_report_1930s.json + README.md to the destination repo. Safe to run at
# any point -- it reports whatever shards have completed so far.
!cd "{CLONE_DIR}" && python scripts/report.py
