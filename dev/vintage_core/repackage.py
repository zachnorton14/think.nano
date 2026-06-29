"""Stage: assemble the vintage-core-filtered bundle from the filter audit (+ any backfill).

Idempotent — run before backfill (kept-only) and again after (kept + backfilled). Output is a
drop-in CORE bundle: `core.yaml` + `eval_meta_data.csv` + `eval_data/<uri>` that scripts/base_eval.py
reads unchanged (via --eval-bundle-dir).

Run:  python -m dev.vintage_core.repackage
"""
import os
import csv
import json
import collections

import yaml

from . import config
from .load import load_tasks

OUT = config.OUT_FILTERED
AUDIT_DIR = os.path.join(OUT, "audit")
BACKFILL_DIR = os.path.join(OUT, "backfill")


def _orig_meta():
    rows = {}
    with open(os.path.join(config.EVAL_BUNDLE_DIR, "eval_meta_data.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows[r["Eval Task"]] = r
    return rows


def _kept_idx(label):
    p = os.path.join(AUDIT_DIR, f"{label}.jsonl")
    out = []
    for line in open(p):
        r = json.loads(line)
        if r["keep"]:
            out.append(r["idx"])
    return out


def _backfill_items(label):
    p = os.path.join(BACKFILL_DIR, f"{label}.jsonl")
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def _baseline(label, items, orig):
    """Chance baseline for centering. Choice structure is unchanged by filtering, so carry the
    upstream value — except boolq, whose class balance shifts (recompute majority-class %)."""
    if label == "boolq":
        golds = [it["gold"] for it in items if "gold" in it]
        if golds:
            top = collections.Counter(golds).most_common(1)[0][1]
            return round(100 * top / len(golds))
    return orig[label]["Random baseline"]


def main():
    tasks = load_tasks()                       # drops excluded, sorted by N
    orig = _orig_meta()
    os.makedirs(os.path.join(OUT, "eval_data"), exist_ok=True)
    yaml_tasks, csv_rows, written = [], [], set()

    for t in tasks:
        label, uri = t["label"], t["dataset_uri"]
        items = [t["data"][i] for i in _kept_idx(label)] + _backfill_items(label)
        # write eval_data/<uri> once per unique file (hellaswag pair shares one, identical sets)
        if uri not in written:
            path = os.path.join(OUT, "eval_data", uri)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                for it in items:
                    f.write(json.dumps(it, ensure_ascii=False) + "\n")
            written.add(uri)
        yaml_tasks.append({
            "label": label, "dataset_uri": uri, "num_fewshot": [t["num_fewshot"]],
            "icl_task_type": t["task_type"], "continuation_delimiter": t["continuation_delimiter"],
        })
        om = orig[label]
        csv_rows.append({
            "Eval Task": label, "Task Category": om["Task Category"], "Task Type": om["Task Type"],
            "#shots": om["#shots"], "#datapoints": len(items),
            "Random baseline": _baseline(label, items, orig),
            "Centered Metric?": om.get("Centered Metric?", ""), "Description": om["Description"],
        })

    yaml.safe_dump({"icl_tasks": yaml_tasks}, open(os.path.join(OUT, "core.yaml"), "w"),
                   sort_keys=False)
    cols = ["Eval Task", "Task Category", "Task Type", "#shots", "#datapoints",
            "Random baseline", "Centered Metric?", "Description"]
    with open(os.path.join(OUT, "eval_meta_data.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(csv_rows)

    total = sum(r["#datapoints"] for r in csv_rows)
    print(f"repackaged {len(yaml_tasks)} tasks, {total} items -> {OUT}")
    for r in csv_rows:
        print(f"  {r['Eval Task']:30s} N={r['#datapoints']:6d} baseline={r['Random baseline']}")


if __name__ == "__main__":
    main()
