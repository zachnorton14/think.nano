"""Regex-filter stats (no API, instant). Post-1930 year = authoritative removal.

Writes only `dev/vintage_core/review/regex_stats.json` (consumed by log.py) and prints
a table. No per-benchmark markdown — review happens in LOG.md.

Run:  python -m dev.vintage_core.regex_report
"""
import os
import json

from . import config
from .load import load_tasks
from .temporal import post_cutoff_years, modern_terms


def compute():
    stats = {}
    for t in load_tasks():
        yr = sum(1 for it in t["data"] if post_cutoff_years(it))
        mo = sum(1 for it in t["data"] if not post_cutoff_years(it) and modern_terms(it))
        n = t["n"]
        stats[t["label"]] = {"n": n, "year_removed": yr, "n_after": n - yr, "modern_only": mo}
    return stats


def main():
    os.makedirs(config.REVIEW_DIR, exist_ok=True)
    stats = compute()
    json.dump(stats, open(os.path.join(config.REVIEW_DIR, "regex_stats.json"), "w"), indent=2)
    print(f"{'task':32s}{'N':>7s}{'yr_rm':>7s}{'after':>7s}{'modern_only':>13s}")
    tot = [0, 0]
    for lab, s in stats.items():
        print(f"{lab:32s}{s['n']:>7d}{s['year_removed']:>7d}{s['n_after']:>7d}{s['modern_only']:>13d}")
        tot[0] += s["n"]; tot[1] += s["year_removed"]
    print(f"{'TOTAL':32s}{tot[0]:>7d}{tot[1]:>7d}{tot[0]-tot[1]:>7d}")
    print("-> dev/vintage_core/review/regex_stats.json (used by LOG.md)")


if __name__ == "__main__":
    main()
