# === Stage 0: clean command (guarded) =======================================
# Deletes generated shards/stats/hits/report from the destination repo so you can
# start from scratch. Does nothing unless you set CONFIRM_WIPE=1 below. Add
# WIPE_BANNED_LIST=1 to also delete the _banned/ list.
#
# IMPORTANT if you previously ran the OLD (flat, over-aggressive) filter: those
# shards were dropped with the wrong rule. Wipe them so the tiered filter can
# reprocess from scratch -- set CONFIRM_WIPE=1 (and WIPE_BANNED_LIST=1 to also
# discard the old flat banned list) for a one-time reset, then set both back to 0.
!cd "{CLONE_DIR}" && CONFIRM_WIPE=0 WIPE_BANNED_LIST=0 python scripts/wipe.py
