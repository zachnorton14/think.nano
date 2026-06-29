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
REGEX_STATS = os.path.join(config.REVIEW_DIR, "regex_stats.json")


def _audit(label):
    p = os.path.join(AUDIT_DIR, f"{label}.jsonl")
    if not os.path.exists(p):
        return None
    return [json.loads(line) for line in open(p)]


def _regex_stats():
    return json.load(open(REGEX_STATS)) if os.path.exists(REGEX_STATS) else {}


def _final_n(task):
    p = os.path.join(config.OUT_FILTERED, "eval_data", task["dataset_uri"])
    return sum(1 for _ in open(p)) if os.path.exists(p) else None


def _target_backfill(n0, kept):
    if n0 < config.BACKFILL_MAX_N:
        return n0 - kept
    if kept < config.BACKFILL_MAX_N <= n0:
        return config.BACKFILL_MAX_N - kept
    return 0


def main():
    tasks = load_tasks()
    rstats = _regex_stats()
    rows, reasons, samples = [], [], []
    tot = Counter()
    for t in tasks:
        label, n0 = t["label"], t["n"]
        a = _audit(label)
        if a is None:
            rs = rstats.get(label)
            if rs:  # regex stage done, LLM pending
                rows.append((label, t["verdict"], n0, rs["year_removed"], "pending",
                             rs["n_after"], "-", "-", "regex-done"))
            else:
                rows.append((label, t["verdict"], n0, "-", "-", "-", "-", "-", "pending"))
            continue
        n_aud = len(a)
        rm_regex = sum(1 for r in a if not r["keep"] and r["src"] == "regex")
        rm_llm = sum(1 for r in a if not r["keep"] and r["src"] == "llm")
        rm_err = sum(1 for r in a if r["src"] == "error")
        kept = sum(1 for r in a if r["keep"])
        final = _final_n(t)
        backfill = (final - kept) if (final is not None and final > kept) else 0
        full = (n_aud == n0)
        if full:
            kept_cell = f"{kept} ({100*kept/n0:.0f}%)"          # kept as % of ORIGINAL
            stage = "done" if final is not None else "filtered"
            # Show actual committed backfill once present; otherwise mark eligibility.
            if final is not None and final > kept:
                backfill = final - kept
            else:
                backfill = "eligible" if _target_backfill(n0, kept) > 0 else "-"
        else:
            kept_cell = f"{kept}/{n_aud} sample"                 # NOT % of orig — a sample
            stage = f"sample {n_aud}/{n0}"
            backfill = "-"
        final_cell = f"{final} ({100*final/n0:.0f}%)" if final is not None else "-"
        rows.append((label, t["verdict"], n0, rm_regex, rm_llm, kept_cell,
                     backfill, final_cell, stage))
        tot["n0"] += n0; tot["regex"] += rm_regex; tot["llm"] += rm_llm
        tot["kept"] += kept; tot["err"] += rm_err
        samples.append((label, t, a))
        for r in a:
            if not r["keep"] and r["src"] == "llm":
                reasons.append(r["reason"])

    now = datetime.date.today().isoformat()
    L = [f"# Vintage CORE — build log\n",
         f"_Regenerated {now} by `python -m dev.vintage_core.log` from on-disk artifacts._\n",
         "Stages: **orig** → filter (**rm_regex** post-1930 years, **rm_llm** entity/register)"
         " → **kept** → **backfill** (if kept < %d after filtering) → **final**. "
         "`kept` shows %% of orig on full runs; `X/n sample` on partial review runs.\n"
         % config.BACKFILL_MAX_N,
         "Dropped entirely: " + ", ".join(f"`{d}`" for d in sorted(config.DROP)) + ".\n",
         "| task | verdict | orig | rm_regex | rm_llm | kept | backfill | final | stage |",
         "|------|---------|-----:|---------:|-------:|-----:|---------:|------:|-------|"]
    for r in rows:
        L.append("| `%s` | %s | %s | %s | %s | %s | %s | %s | %s |" % r)
    if tot["n0"]:
        L.append("| **TOTAL** | | **%d** | **%d** | **%d** | **%d** | | | |"
                 % (tot["n0"], tot["regex"], tot["llm"], tot["kept"]))
    if tot["err"]:
        L.append("\n_LLM/parse errors (defaulted to keep, flagged for review): %d_" % tot["err"])
    if reasons:
        L.append("\n## Top LLM removal reasons\n")
        for reason, c in Counter(reasons).most_common(12):
            L.append(f"- {c}× {reason}")

    # LLM-filter samples per benchmark (the review surface): 8 removed + 2 kept, with reasons.
    # The FULL list of every removed item lives in the audit jsonl (see path below).
    if samples:
        from .prompts import render_item
        L.append(f"\n## LLM filter samples (8 removed + 2 kept per benchmark)\n")
        L.append(f"_Full per-item audit (every keep/remove + reason): "
                 f"`{AUDIT_DIR}/<label>.jsonl`_\n")
        for label, t, a in samples:
            rm = [r for r in a if not r["keep"] and r["src"] in ("llm", "error")]
            kp = [r for r in a if r["keep"] and r["src"] == "llm"]
            if not rm and not kp:
                continue
            L.append(f"### `{label}`  ({len(rm)} LLM-removed in this audit)")
            for r in rm[:8]:
                txt = render_item(t["data"][r["idx"]], t["task_type"]).replace("\n", " ")[:130]
                L.append(f"- ❌ _{r['reason']}_ — {txt}")
            for r in kp[:2]:
                txt = render_item(t["data"][r["idx"]], t["task_type"]).replace("\n", " ")[:130]
                L.append(f"- ✅ _{r['reason']}_ — {txt}")
    open(LOG_PATH, "w").write("\n".join(L) + "\n")
    print(f"wrote {LOG_PATH} ({len(rows)} tasks)")


if __name__ == "__main__":
    main()
