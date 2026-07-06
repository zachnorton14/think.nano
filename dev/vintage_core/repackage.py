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

# Count-free descriptions for the packaged Vintage CORE construct. Upstream descriptions embed
# original dataset sizes (which become stale after filtering), and ARC-Challenge is incorrectly
# described there as ARC-Easy.
VINTAGE_DESCRIPTIONS = {
    "bigbench_repeat_copy_logic": (
        "Symbolic instruction-following tasks requiring exact repetition of words under simple "
        "counting and ordering rules."
    ),
    "copa": (
        "Cause-and-effect commonsense questions requiring selection between two possible causes "
        "or consequences."
    ),
    "bigbench_operators": (
        "Symbolic problems requiring application of newly defined mathematical operators to "
        "compute an exact result."
    ),
    "agi_eval_lsat_ar": (
        "LSAT-style analytical reasoning games requiring deductions from a passage and a set of "
        "logical constraints."
    ),
    "winograd": (
        "Winograd schema questions testing semantic resolution of an ambiguous pronoun between "
        "two candidate antecedents."
    ),
    "openbook_qa": (
        "Four-choice elementary science questions testing factual knowledge and physical or "
        "scientific reasoning."
    ),
    "arc_challenge": (
        "The difficult ARC science split: four-choice grade-school questions requiring applied, "
        "often multi-step scientific reasoning."
    ),
    "commonsense_qa": (
        "Four-choice questions testing everyday commonsense knowledge and basic reasoning about "
        "people, places, and objects."
    ),
    "winogrande": (
        "Two-choice sentence-completion schemas testing commonsense coreference and semantic "
        "plausibility."
    ),
    "piqa": (
        "Two-choice physical commonsense questions testing practical knowledge of objects, tools, "
        "and everyday actions."
    ),
    "jeopardy": (
        "Exact-answer general-knowledge clues drawn from literature, history, word origins, and "
        "science categories."
    ),
    "arc_easy": (
        "The easier ARC science split: four-choice grade-school questions testing basic scientific "
        "knowledge and reasoning."
    ),
    "boolq": (
        "Short passages followed by yes-or-no reading-comprehension questions scored as multiple "
        "choice."
    ),
    "lambada_openai": (
        "Book passages requiring exact prediction of the final word from the preceding context."
    ),
    "coqa": (
        "Conversational passage-based questions requiring an exact short answer using the story "
        "and preceding dialogue."
    ),
    "bigbench_language_identification": (
        "Four-choice identification of the language used in a presented sentence."
    ),
    "hellaswag_zeroshot": (
        "Zero-shot selection of the most plausible continuation for an everyday scenario."
    ),
    "hellaswag": (
        "Few-shot selection of the most plausible continuation for an everyday scenario."
    ),
    "squad": (
        "Passage-based reading comprehension requiring an exact answer supported by the supplied "
        "context."
    ),
    "bigbench_qa_wikidata": (
        "Exact factual completions derived from structured Wikidata relations."
    ),
}


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
    with open(os.path.join(config.EVAL_BUNDLE_DIR, "core.yaml"), encoding="utf-8") as f:
        upstream_tasks = {
            task["label"]: task for task in yaml.safe_load(f)["icl_tasks"]
        }
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
        # Preserve the complete upstream task contract (including optional fields such as
        # jeopardy's ``has_categories``) while excluding only tasks dropped by load_tasks().
        yaml_tasks.append(dict(upstream_tasks[label]))
        om = orig[label]
        csv_rows.append({
            "Eval Task": label, "Task Category": om["Task Category"], "Task Type": om["Task Type"],
            "#shots": om["#shots"], "#datapoints": len(items),
            "Random baseline": _baseline(label, items, orig),
            "Centered Metric?": om.get("Centered Metric?", ""),
            "Description": VINTAGE_DESCRIPTIONS[label],
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

    # Keep bundle-facing documentation synchronized with the data just packaged.
    from .gauntlet import main as write_gauntlet
    write_gauntlet()


if __name__ == "__main__":
    main()
