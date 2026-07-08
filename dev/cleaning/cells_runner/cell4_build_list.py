# === Stage 1: build (or load) the banned list ===============================
# Builds the 1930s banned list from croqaz + allow-list + extras, prints the
# total term count, and uploads it under _banned/ in the destination repo.
# Re-running loads the cached list; set FORCE_REBUILD_LIST=1 to rebuild.
!cd "{CLONE_DIR}" && FORCE_REBUILD_LIST=0 python scripts/build_list.py
