"""Generate the filtered Vintage CORE EVAL_GAUNTLET.md from bundle metadata.

Run after repackage:
  python -m dev.vintage_core.gauntlet
"""
import csv
import os
from collections import defaultdict

import yaml

from . import config

OUT_PATH = os.path.join(config.OUT_FILTERED, "EVAL_GAUNTLET.md")


def _rows():
    path = os.path.join(config.OUT_FILTERED, "eval_meta_data.csv")
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _task_order():
    path = os.path.join(config.OUT_FILTERED, "core.yaml")
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return [t["label"] for t in cfg["icl_tasks"]]


def _fmt_baseline(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{v:g}%"


def generate():
    rows_by_label = {r["Eval Task"]: r for r in _rows()}
    ordered = [rows_by_label[label] for label in _task_order() if label in rows_by_label]
    by_category = defaultdict(list)
    for row in ordered:
        by_category[row["Task Category"]].append(row)

    lines = [
        "# Vintage CORE Filtered - Eval Gauntlet",
        "",
        "This is the Artifact A filtered CORE bundle: every kept benchmark passed the",
        "1930-cutoff regex plus LLM temporal filter. Dropped benchmarks are excluded,",
        "and low-N tasks may be backfilled by `dev.vintage_core.backfill` after review.",
        "",
        f"Bundle: `{config.OUT_FILTERED}`",
        "",
        "## Scoring",
        "",
        "The existing CORE scorer is unchanged. Multiple-choice and schema tasks use",
        "accuracy, language-modeling tasks use exact continuation match, and centered",
        "metrics use the random baselines in `eval_meta_data.csv`.",
        "",
    ]

    for category in sorted(by_category):
        lines += [f"## {category.title()}", ""]
        for row in by_category[category]:
            lines += [
                f"### `{row['Eval Task']}`",
                "",
                f"- Task type: {row['Task Type']}",
                f"- Few-shot examples: {row['#shots']}",
                f"- Filtered datapoints: {row['#datapoints']}",
                f"- Random baseline: {_fmt_baseline(row['Random baseline'])}",
                f"- Description: {row['Description'].strip()}",
                "",
            ]
    return "\n".join(lines).rstrip() + "\n"


def main():
    os.makedirs(config.OUT_FILTERED, exist_ok=True)
    text = generate()
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
