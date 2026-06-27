"""Stage 3-4: filter each benchmark. Post-1930 year = authoritative regex removal (no LLM).
Everything else is judged by the LLM in BATCHES (one stable cacheable system prompt + ~15
items/call) for efficiency, with a single-item fallback on any batch failure.

  # process all benchmarks (smallest-N first), writes audit + LOG.md samples:
  python -m dev.vintage_core.filter --workers 6
  # review heavy tasks on a sample first:
  python -m dev.vintage_core.filter --tasks boolq,squad,coqa,hellaswag --max-items 60
  # plumbing test, no API:
  python -m dev.vintage_core.filter --no-llm --max-items 40
"""
import os
import time
import json
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, prompts
from .load import load_tasks
from .temporal import annotate
from .client import chat_json, map_concurrent, USAGE, usage_summary

AUDIT_DIR = os.path.join(config.OUT_FILTERED, "audit")
BATCH = 10
BATCH_TOKENS = 12000  # reasoning model: ~600 out tok/item, so 10 items needs ~6-8k + headroom


def load_audit(label):
    """Existing audit as {idx: record} (resume; last write wins)."""
    p = os.path.join(AUDIT_DIR, f"{label}.jsonl")
    out = {}
    if os.path.exists(p):
        for line in open(p):
            r = json.loads(line)
            out[r["idx"]] = r
    return out


def _regex_record(ann):
    return {"keep": False, "src": "regex", "reason": f"post-1930 year {ann['years_found']}", **ann}


def decide(item, task_type, use_llm):
    """Single-item decision (fallback path / --no-llm)."""
    ann = annotate(item)
    if ann["regex_remove"]:
        return _regex_record(ann)
    if not use_llm:
        return {"keep": True, "src": "regex-only", "reason": "no post-1930 year (no-llm)", **ann}
    msgs = prompts.filter_messages(item, task_type, ann)
    for budget in (768, 1536):
        try:
            out = chat_json(msgs, config.FILTER_MODEL, config.FILTER_BASE_URL, max_tokens=budget)
            return {"keep": bool(out.get("keep", True)), "src": "llm",
                    "reason": str(out.get("reason", ""))[:120], **ann}
        except Exception as e:  # noqa: BLE001
            last = e
    return {"keep": True, "src": "error", "reason": f"llm error: {str(last)[:90]}", **ann}


def decide_batch(batch):
    """batch: list of (item, task_type, ann). Returns aligned records. Batch call with
    per-item fallback for any id the model drops or a parse failure."""
    payload = [(i, it, tt, ann) for i, (it, tt, ann) in enumerate(batch)]
    out = [None] * len(batch)
    try:
        arr = chat_json(prompts.filter_batch_messages(payload), config.FILTER_MODEL,
                        config.FILTER_BASE_URL, max_tokens=BATCH_TOKENS)
        by_id = {int(o["id"]): o for o in arr if isinstance(o, dict) and "id" in o}
    except Exception:  # noqa: BLE001
        by_id = {}
    for i, (it, tt, ann) in enumerate(batch):
        o = by_id.get(i)
        if o is None:                       # dropped/parse-failed -> single-item fallback
            out[i] = decide(it, tt, use_llm=True)
        else:
            out[i] = {"keep": bool(o.get("keep", True)), "src": "llm",
                      "reason": str(o.get("reason", ""))[:120], **ann}
    return out


def pick_indices(n, sample, max_items):
    """sample>0 -> strided across the whole file (representative review);
    max_items>0 -> first N; else all."""
    if sample > 0 and n > sample:
        return sorted(set(int(round(i * (n - 1) / (sample - 1))) for i in range(sample)))
    if max_items > 0:
        return list(range(min(n, max_items)))
    return list(range(n))


def run(tasks_filter, sample, max_items, workers, use_llm):
    os.makedirs(AUDIT_DIR, exist_ok=True)
    sel = [t for t in load_tasks() if not (tasks_filter and t["label"] not in tasks_filter)]
    # TRUE total upfront (so progress shows X / <real total>, not a cumulative denominator)
    grand_total = sum(len(pick_indices(t["n"], sample, max_items)) for t in sel)
    grand_done = 0
    t_start = time.time()
    for t in sel:
        path = os.path.join(AUDIT_DIR, f"{t['label']}.jsonl")
        records = load_audit(t["label"])          # RESUME: keep what's already done
        idxs = pick_indices(t["n"], sample, max_items)
        todo = []
        for oi in idxs:
            if oi in records and records[oi].get("src") != "error":
                continue                          # already audited -> skip (retry errors)
            ann = annotate(t["data"][oi])
            if ann["regex_remove"]:
                records[oi] = {"idx": oi, **_regex_record(ann)}
            elif not use_llm:
                records[oi] = {"idx": oi, "keep": True, "src": "regex-only",
                               "reason": "no post-1930 year (no-llm)", **ann}
            else:
                todo.append((oi, t["data"][oi], t["task_type"], ann))
        grand_done += len(idxs) - len(todo)   # regex-handled / already-done count immediately
        # process LLM batches concurrently; APPEND each completed batch (interruption-safe)
        batches = [todo[k:k + BATCH] for k in range(0, len(todo), BATCH)]
        af = open(path, "a")
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(decide_batch, [(x[1], x[2], x[3]) for x in b]): b for b in batches}
            for n, fut in enumerate(as_completed(futs), 1):
                b = futs[fut]
                for (oi, _, _, _), rec in zip(b, fut.result()):
                    rec = {"idx": oi, **rec}
                    records[oi] = rec
                    af.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    grand_done += 1
                af.flush()
                if n % 5 == 0 or n == len(batches):
                    rate = grand_done / max(time.time() - t_start, 1e-9)
                    eta = (grand_total - grand_done) / max(rate, 1e-9)
                    print(f"  [{t['label']}] {n}/{len(batches)} batches | "
                          f"{grand_done}/{grand_total} items | {rate:.1f}/s | ETA {eta/60:.0f}m | "
                          f"{usage_summary()}", flush=True)
        af.close()
        # rewrite sorted + deduped (clean final audit)
        with open(path, "w") as f:
            for oi in sorted(records):
                f.write(json.dumps(records[oi], ensure_ascii=False) + "\n")
        kept = sum(r["keep"] for r in records.values())
        print(f"DONE {t['label']:30s} kept {kept}/{len(records)} "
              f"({100*kept/max(len(records),1):.0f}%)", flush=True)
    print(f"\nTOTAL {usage_summary()} | {time.time()-t_start:.0f}s")
    print(f"audit -> {AUDIT_DIR} ; run `python -m dev.vintage_core.log` for LOG.md + samples")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="")
    ap.add_argument("--sample", type=int, default=0, help="N items STRIDED across the file (review)")
    ap.add_argument("--max-items", type=int, default=-1, help="first N items")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--no-llm", action="store_true")
    a = ap.parse_args()
    tf = set(s for s in a.tasks.split(",") if s)
    run(tf, a.sample, a.max_items, a.workers, use_llm=not a.no_llm)


if __name__ == "__main__":
    main()
