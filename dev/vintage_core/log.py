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
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TRACKED_FILTERED = os.path.join(REPO_ROOT, "artifacts", "vintage-core-filtered", "eval_data")
TRACKED_RESTYLED = os.path.join(REPO_ROOT, "artifacts", "vintage-core-restyle", "eval_data")

# Stable, deliberately small showcase spanning the principal scoring contracts.  Each
# needle identifies exactly one row in the tracked filtered bundle.  Generation fails
# closed if a row disappears, stops being restyled, or changes its scoring target.
RESTYLE_SAMPLE_SPECS = (
    ("copa", "The man turned on the faucet", "cause-and-effect multiple choice"),
    ("jeopardy", "Accused of accepting bribes", "exact-answer knowledge clue"),
    ("boolq", "Ladies may wear a long", "passage-based multiple choice"),
    (
        "hellaswag",
        "Clean and jerk: A lady walks to a barbell. She bends down and grabs the pole.",
        "scenario completion",
    ),
)


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
    return n0 - kept if n0 < config.BACKFILL_MAX_N else 0


def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _restyle_samples(tasks):
    """Return curated released before/after pairs and verify scoring invariants."""
    from .prompts import render_item

    task_by_label = {task["label"]: task for task in tasks}
    pairs = []
    for label, needle, description in RESTYLE_SAMPLE_SPECS:
        task = task_by_label[label]
        rel = task["dataset_uri"]
        filtered = _read_jsonl(os.path.join(TRACKED_FILTERED, rel))
        restyled = _read_jsonl(os.path.join(TRACKED_RESTYLED, rel))
        if len(filtered) != len(restyled):
            raise ValueError(f"{label}: filtered/restyled row counts differ")

        matches = [
            idx for idx, item in enumerate(filtered)
            if needle in render_item(item, task["task_type"])
        ]
        if len(matches) != 1:
            raise ValueError(f"{label}: expected one restyle sample match, found {matches}")
        idx = matches[0]
        before, after = filtered[idx], restyled[idx]
        if before == after:
            raise ValueError(f"{label} idx={idx}: selected row is not restyled")

        for key in ("choices", "gold", "continuation"):
            if key in before and before[key] != after.get(key):
                raise ValueError(f"{label} idx={idx}: scoring field {key!r} changed")

        before_text = render_item(before, task["task_type"]).replace("\n", " ")
        after_text = render_item(after, task["task_type"]).replace("\n", " ")
        pairs.append((label, description, before_text, after_text))
    return pairs


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
        rm_llm = sum(1 for r in a if not r["keep"] and r["src"] != "regex")
        rm_err = sum(1 for r in a if r["src"] == "error" and r["keep"])
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
            if not r["keep"] and r["src"] != "regex":
                reasons.append(r["reason"])

    now = datetime.date.today().isoformat()
    L = [f"# Vintage CORE — build log\n",
         f"_Regenerated {now} by `python -m dev.vintage_core.log` from on-disk artifacts._\n",
         "Stages: **orig** → filter (**rm_regex** post-1930 years, **rm_llm** entity/register)"
         " → **kept** → **backfill** (when original N < %d) → **final**. "
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

    restyle_samples = _restyle_samples(tasks)
    L.append("\n## Restyle examples\n")
    L.append(
        "_Representative released before/after scoring items from the tracked filtered and "
        "restyled bundles. Choices, gold labels, and exact-answer continuations remain "
        "unchanged; only the prompt or context is restyled._\n"
    )
    for sample_idx, (label, description, before_text, after_text) in enumerate(restyle_samples):
        L.append(f"### `{label}` — {description}")
        L.append("")
        L.append(f"> **Filtered:** {before_text}\n>")
        L.append(f"> **Restyled:** {after_text}")
        if sample_idx + 1 < len(restyle_samples):
            L.append("")
    open(LOG_PATH, "w").write("\n".join(L) + "\n")
    print(f"wrote {LOG_PATH} ({len(rows)} tasks)")


if __name__ == "__main__":
    main()
