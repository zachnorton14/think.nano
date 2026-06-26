"""Load the upstream CORE eval bundle, ordered smallest-N first (drops excluded)."""
import os
import json

import yaml

from . import config


def load_tasks(include_dropped=False):
    """Return a list of task dicts ordered by N ascending.

    Each: {label, task_type, num_fewshot, dataset_uri, continuation_delimiter, data, n, verdict}.
    """
    cfg = yaml.safe_load(open(os.path.join(config.EVAL_BUNDLE_DIR, "core.yaml")))
    tasks = []
    for t in cfg["icl_tasks"]:
        label = t["label"]
        if not include_dropped and label in config.DROP:
            continue
        path = os.path.join(config.EVAL_BUNDLE_DIR, "eval_data", t["dataset_uri"])
        data = [json.loads(line) for line in open(path, encoding="utf-8")]
        tasks.append({
            "label": label,
            "task_type": t["icl_task_type"],
            "num_fewshot": t["num_fewshot"][0],
            "dataset_uri": t["dataset_uri"],
            "continuation_delimiter": t.get("continuation_delimiter", " "),
            "data": data,
            "n": len(data),
            "verdict": config.VERDICT.get(label, "?"),
        })
    tasks.sort(key=lambda x: x["n"])
    return tasks
