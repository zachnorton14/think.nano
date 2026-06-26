"""Stage 3-4: filter each benchmark (regex-authoritative years + LLM judge), write a
per-item audit and an 8-sample review file per benchmark (Gate 1).

  # preview 8 items/benchmark for review BEFORE committing (smallest-N first):
  python -m dev.vintage_core.filter --preview 8 --tasks copa,bigbench_operators
  # full run once the prompt is approved:
  python -m dev.vintage_core.filter --workers 8
  # test the plumbing with no credits (regex-only, no LLM calls):
  python -m dev.vintage_core.filter --no-llm --preview 8
"""
import os
import json
import argparse

from . import config, prompts
from .load import load_tasks
from .temporal import annotate
from .client import chat_json, map_concurrent

AUDIT_DIR = os.path.join(config.OUT_FILTERED, "audit")
REVIEW_DIR = os.path.join(config.OUT_FILTERED, "review")


def decide(item, task_type, use_llm):
    """Return audit record for one item. Post-1930 year is authoritative (no LLM needed)."""
    ann = annotate(item)
    if ann["regex_remove"]:
        return {"keep": False, "src": "regex",
                "reason": f"post-1930 year {ann['years_found']}", **ann}
    if not use_llm:
        return {"keep": True, "src": "regex-only", "reason": "no post-1930 year (no-llm mode)", **ann}
    out = chat_json(prompts.filter_messages(item, task_type, ann),
                    config.FILTER_MODEL, max_tokens=64)
    return {"keep": bool(out.get("keep", True)), "src": "llm",
            "reason": str(out.get("reason", ""))[:120], **ann}


def _write_review(label, task_type, data, records):
    removed = [(i, r) for i, r in enumerate(records) if not r["keep"]]
    lines = [f"# Filter review — `{label}`  ({len(removed)}/{len(records)} removed)\n",
             "8 removed samples for approval (Gate 1). Edit the filter prompt if these look wrong.\n"]
    for i, r in removed[:8]:
        lines.append("```")
        lines.append(prompts.render_item(data[i], task_type))
        lines.append(f">>> REMOVED [{r['src']}]: {r['reason']}")
        lines.append("```")
    if not removed:
        lines.append("_(nothing removed)_")
    open(os.path.join(REVIEW_DIR, f"{label}.filter.md"), "w").write("\n".join(lines) + "\n")


def run(tasks_filter, max_items, preview, workers, use_llm):
    os.makedirs(AUDIT_DIR, exist_ok=True)
    os.makedirs(REVIEW_DIR, exist_ok=True)
    print(f"{'task':32s}{'seen':>7s}{'kept':>7s}{'removed':>9s}{'%rm':>7s}  (smallest-N first)")
    for t in load_tasks():
        if tasks_filter and t["label"] not in tasks_filter:
            continue
        data = t["data"]
        if preview:
            data = data[:preview]
        elif max_items > 0:
            data = data[:max_items]
        records = map_concurrent(lambda it: decide(it, t["task_type"], use_llm), data, workers,
                                 on_error=lambda it, e: {"keep": True, "src": "error",
                                                         "reason": str(e)[:120],
                                                         "years_found": [], "modern_terms": [],
                                                         "regex_remove": False})
        kept = sum(r["keep"] for r in records)
        # audit jsonl (one row per item) unless this is just a preview
        if not preview:
            with open(os.path.join(AUDIT_DIR, f"{t['label']}.jsonl"), "w") as f:
                for i, r in enumerate(records):
                    f.write(json.dumps({"idx": i, **r}, ensure_ascii=False) + "\n")
        _write_review(t["label"], t["task_type"], data, records)
        rm = len(records) - kept
        print(f"{t['label']:32s}{len(records):>7d}{kept:>7d}{rm:>9d}{100*rm/len(records):>6.1f}%")
    tag = "PREVIEW" if preview else ("NO-LLM" if not use_llm else "FULL")
    print(f"\n[{tag}] review files -> {REVIEW_DIR}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="", help="comma-separated labels (default: all)")
    ap.add_argument("--max-items", type=int, default=-1)
    ap.add_argument("--preview", type=int, default=0, help="only N items/task, write review only")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-llm", action="store_true", help="regex-only, no API calls (plumbing test)")
    a = ap.parse_args()
    tf = set(s for s in a.tasks.split(",") if s)
    run(tf, a.max_items, a.preview, a.workers, use_llm=not a.no_llm)


if __name__ == "__main__":
    main()
