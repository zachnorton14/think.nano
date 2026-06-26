"""Regenerate dev/vintage_core/LOG.md from on-disk artifacts (single source of truth,
so the log can never drift from reality).

Tracks, per benchmark, the size at each stage: original -> filtered (regex/LLM split)
-> backfilled -> final. Run after any stage:  python -m dev.vintage_core.log
"""
import os
import json
import datetime
from collections import Counter

from . import config
from .load import load_tasks

LOG_PATH = os.path.join(os.path.dirname(__file__), "LOG.md")
AUDIT_DIR = os.path.join(config.OUT_FILTERED, "audit")


def _audit(label):
    p = os.path.join(AUDIT_DIR, f"{label}.jsonl")
    if not os.path.exists(p):
        return None
    return [json.loads(line) for line in open(p)]


def _final_n(label):
    p = os.path.join(config.OUT_FILTERED, "eval_data", f"{label}.jsonl")
    return sum(1 for _ in open(p)) if os.path.exists(p) else None


def main():
    tasks = load_tasks()
    rows, reasons = [], []
    tot = Counter()
    for t in tasks:
        label, n0 = t["label"], t["n"]
        a = _audit(label)
        if a is None:
            rows.append((label, t["verdict"], n0, "-", "-", "-", "-", "-", "pending"))
            continue
        n_aud = len(a)
        rm_regex = sum(1 for r in a if not r["keep"] and r["src"] == "regex")
        rm_llm = sum(1 for r in a if not r["keep"] and r["src"] == "llm")
        kept = sum(1 for r in a if r["keep"])
        final = _final_n(label)
        backfill = (final - kept) if (final is not None and final > kept) else 0
        partial = "" if n_aud == n0 else f" (audited {n_aud}/{n0})"
        rows.append((label, t["verdict"], n0, rm_regex, rm_llm, kept,
                     backfill or "-", final if final is not None else "-",
                     ("done" if final is not None else "filtered") + partial))
        tot["n0"] += n0; tot["regex"] += rm_regex; tot["llm"] += rm_llm; tot["kept"] += kept
        for r in a:
            if not r["keep"] and r["src"] == "llm":
                reasons.append(r["reason"])

    now = datetime.date.today().isoformat()
    L = [f"# Vintage CORE — build log\n",
         f"_Regenerated {now} by `python -m dev.vintage_core.log` from on-disk artifacts._\n",
         "Stages: **orig** → filter (**rm_regex** post-1930 years, **rm_llm** entity/register)"
         " → **kept** → **backfill** (N≤%d) → **final**.\n" % config.BACKFILL_MAX_N,
         "Dropped entirely: " + ", ".join(f"`{d}`" for d in sorted(config.DROP)) + ".\n",
         "| task | verdict | orig | rm_regex | rm_llm | kept | backfill | final | stage |",
         "|------|---------|-----:|---------:|-------:|-----:|---------:|------:|-------|"]
    for r in rows:
        L.append("| `%s` | %s | %s | %s | %s | %s | %s | %s | %s |" % r)
    if tot["n0"]:
        L.append("| **TOTAL** | | **%d** | **%d** | **%d** | **%d** | | | |"
                 % (tot["n0"], tot["regex"], tot["llm"], tot["kept"]))
    if reasons:
        L.append("\n## Top LLM removal reasons\n")
        for reason, c in Counter(reasons).most_common(15):
            L.append(f"- {c}× {reason}")
    open(LOG_PATH, "w").write("\n".join(L) + "\n")
    print(f"wrote {LOG_PATH} ({len(rows)} tasks)")


if __name__ == "__main__":
    main()
