"""Dry-run stats — verification step 1. No API calls, no spend.

Per benchmark (smallest N first): regex-flagged temporal fraction, the verdict, a
LOWER-BOUND projected N after regex-only removal, and whether backfill kicks in.
The LLM judge will remove at least this many (it also catches entity/register cases
regex misses), so real survivors <= projected here.

Run: python -m dev.vintage_core.stats     (from repo root)
"""
from . import config
from .load import load_tasks
from .temporal import regex_flag, post_cutoff_years


def main():
    tasks = load_tasks()
    print(f"{'task':32s}{'verdict':14s}{'N':>7s}{'regex_flag':>11s}{'%':>7s}"
          f"{'proj_N':>8s}{'backfill?':>10s}")
    print("-" * 89)
    tot_n = tot_flag = 0
    for t in tasks:
        n = t["n"]
        flagged = sum(1 for it in t["data"] if regex_flag(it))
        proj = n - flagged
        backfill = "yes" if (n <= config.BACKFILL_MAX_N and flagged > 0) else ""
        tot_n += n
        tot_flag += flagged
        print(f"{t['label']:32s}{t['verdict']:14s}{n:>7d}{flagged:>11d}"
              f"{100*flagged/n:>6.1f}%{proj:>8d}{backfill:>10s}")
    print("-" * 89)
    print(f"{'TOTAL (kept tasks)':32s}{'':14s}{tot_n:>7d}{tot_flag:>11d}"
          f"{100*tot_flag/tot_n:>6.1f}%{tot_n-tot_flag:>8d}")
    print(f"\nDropped (excluded): {sorted(config.DROP)}")
    print(f"Backfill threshold: N <= {config.BACKFILL_MAX_N}")

    # spot example of regex-caught items per heavy task, to sanity-check the prescan
    print("\nSample regex-flagged years (first task with hits):")
    for t in tasks:
        for it in t["data"]:
            yrs = post_cutoff_years(it)
            if yrs:
                print(f"  {t['label']}: years={yrs[:5]}")
                break
        else:
            continue
        break


if __name__ == "__main__":
    main()
