"""Stage: generate period-valid replacements for low-N vintage CORE tasks.

Preview first:
  python -m dev.vintage_core.backfill --preview-size 10

Commit after prompt/review approval:
  python -m dev.vintage_core.backfill --commit

The filter audit is the source of truth. This stage never reruns filtering; it rewrites
removed items for benchmarks whose kept count fell below the configured backfill target.
"""
import argparse
import copy
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, prompts
from .client import RateLimited, chat_json, cooldown_wait, usage_summary
from .load import load_tasks
from .temporal import annotate

AUDIT_DIR = os.path.join(config.OUT_FILTERED, "audit")
BACKFILL_DIR = os.path.join(config.OUT_FILTERED, "backfill")
BOOLQ_SAMPLE_SEED = 1930
DEFAULT_MAX_TOKENS = 2048


class ValidationError(ValueError):
    """Generated item failed a deterministic backfill invariant."""


def _audit_records(label):
    path = os.path.join(AUDIT_DIR, f"{label}.jsonl")
    if not os.path.exists(path):
        raise FileNotFoundError(f"missing filter audit for {label}: {path}")
    records = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            records[int(r["idx"])] = r
    return records


def _existing_backfill(label):
    path = os.path.join(BACKFILL_DIR, f"{label}.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _target_count(original_n, kept_n):
    if original_n < config.BACKFILL_MAX_N:
        return original_n - kept_n
    if kept_n < config.BACKFILL_MAX_N <= original_n:
        return config.BACKFILL_MAX_N - kept_n
    return 0


def _target_sources(task):
    records = _audit_records(task["label"])
    if len(records) != task["n"]:
        raise RuntimeError(f"{task['label']} audit is partial: {len(records)}/{task['n']}")
    kept_n = sum(1 for r in records.values() if r["keep"])
    need = _target_count(task["n"], kept_n)
    if need <= 0:
        return [], kept_n, records

    removed = [records[i] for i in sorted(records) if not records[i]["keep"]]
    if need > len(removed):
        raise RuntimeError(f"{task['label']} needs {need} backfills but only {len(removed)} removed")

    if task["n"] < config.BACKFILL_MAX_N:
        chosen = removed
    else:
        rng = random.Random(BOOLQ_SAMPLE_SEED)
        chosen = sorted(rng.sample(removed, need), key=lambda r: r["idx"])
    return chosen, kept_n, records


def eligible_tasks(tasks_filter=None):
    tasks = []
    for task in load_tasks():
        if tasks_filter and task["label"] not in tasks_filter:
            continue
        sources, kept_n, _ = _target_sources(task)
        if sources:
            tasks.append((task, sources, kept_n))
    return tasks


def _expected_keys(task_type):
    if task_type == "multiple_choice":
        return {"query", "choices", "gold"}
    if task_type == "schema":
        return {"context_options", "continuation", "gold"}
    if task_type == "language_modeling":
        return {"context", "continuation"}
    raise ValidationError(f"unsupported task type: {task_type}")


def _require_str(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string")


def _choice_list_is_fixed(choices):
    lowered = [c.lower() for c in choices if isinstance(c, str)]
    if len(lowered) != len(choices):
        return False
    if lowered in (["no", "yes"], ["yes", "no"]):
        return True
    return all(len(c) == 1 and "a" <= c <= "z" for c in lowered)


def _validate_core(generated, original, task_type):
    if not isinstance(generated, dict):
        raise ValidationError("response is not a JSON object")
    keys = _expected_keys(task_type)
    if not (keys & generated.keys()):
        for wrapper in ("item", "new_item", "replacement", "output"):
            nested = generated.get(wrapper)
            if isinstance(nested, dict):
                generated = nested
                break
    missing = keys - generated.keys()
    if missing:
        raise ValidationError(f"missing keys: {sorted(missing)}")

    item = {k: copy.deepcopy(generated[k]) for k in keys}
    if task_type == "multiple_choice":
        _require_str(item["query"], "query")
        choices = item["choices"]
        if not isinstance(choices, list) or len(choices) != len(original["choices"]):
            raise ValidationError("choice count changed")
        if _choice_list_is_fixed(original["choices"]) and choices != original["choices"]:
            raise ValidationError("fixed choice labels changed")
        for i, choice in enumerate(choices):
            _require_str(choice, f"choices[{i}]")
        if not isinstance(item["gold"], int) or not 0 <= item["gold"] < len(choices):
            raise ValidationError("gold index invalid")

    elif task_type == "schema":
        options = item["context_options"]
        if not isinstance(options, list) or len(options) != len(original["context_options"]):
            raise ValidationError("context option count changed")
        for i, option in enumerate(options):
            _require_str(option, f"context_options[{i}]")
        _require_str(item["continuation"], "continuation")
        if not isinstance(item["gold"], int) or not 0 <= item["gold"] < len(options):
            raise ValidationError("gold index invalid")

    elif task_type == "language_modeling":
        _require_str(item["context"], "context")
        _require_str(item["continuation"], "continuation")

    ann = annotate(item)
    if ann["regex_remove"]:
        raise ValidationError(f"post-1930 years found: {ann['years_found']}")
    return item


def _rewrite_once(original, task_type, max_tokens):
    return chat_json(
        prompts.backfill_messages(original, task_type),
        config.REWRITE_MODEL,
        config.REWRITE_BASE_URL,
        temperature=0.0,
        max_tokens=max_tokens,
    )


def _rewrite_valid(source, task, max_tokens, retries):
    original = task["data"][source["idx"]]
    last = None
    for attempt in range(retries):
        try:
            generated = _rewrite_once(original, task["task_type"], max_tokens)
            item = _validate_core(generated, original, task["task_type"])
            item["backfilled"] = True
            item["source_idx"] = source["idx"]
            item["source_reason"] = source.get("reason", "")
            item["source_src"] = source.get("src", "")
            return item
        except RateLimited as e:
            last = e
            time.sleep(min(max(cooldown_wait(), 1.0), 60.0))
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt + 1 < retries:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"{task['label']} source_idx={source['idx']} failed validation: {last}")


def _review_path(label):
    return os.path.join(config.REVIEW_DIR, f"backfill_{label}.md")


def _write_review(label, rows, committed):
    os.makedirs(config.REVIEW_DIR, exist_ok=True)
    lines = [
        f"# Backfill review: `{label}`",
        "",
        f"Mode: {'commit' if committed else 'preview'}",
        f"Items: {len(rows)}",
        "",
    ]
    for n, row in enumerate(rows, 1):
        original = prompts.render_item(row["original"], row["task_type"]).replace("\n", " ")
        generated = prompts.render_item(row["generated"], row["task_type"]).replace("\n", " ")
        lines += [
            f"## {n}. source_idx={row['source_idx']} ({row['source_reason']})",
            "",
            "**Original removed item**",
            "",
            original,
            "",
            "**Generated replacement**",
            "",
            generated,
            "",
        ]
    with open(_review_path(label), "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def _append_item(label, item):
    os.makedirs(BACKFILL_DIR, exist_ok=True)
    path = os.path.join(BACKFILL_DIR, f"{label}.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _rewrite_many(task, sources, workers, max_tokens, retries):
    if workers <= 1:
        for source in sources:
            yield source, _rewrite_valid(source, task, max_tokens, retries)
        return
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_rewrite_valid, source, task, max_tokens, retries): source
                for source in sources}
        for fut in as_completed(futs):
            source = futs[fut]
            yield source, fut.result()


def run(tasks_filter, commit, preview_size, workers, max_items, retries, max_tokens):
    targets = eligible_tasks(tasks_filter)
    if not targets:
        print("no backfill-eligible tasks")
        return

    for task, sources, kept_n in targets:
        label = task["label"]
        existing = _existing_backfill(label)
        existing_by_source = {int(it["source_idx"]): it for it in existing if "source_idx" in it}
        if len(existing_by_source) != len(existing):
            raise RuntimeError(f"{label} backfill has records missing source_idx")
        if len(existing_by_source) > len(sources):
            raise RuntimeError(f"{label} backfill has {len(existing)} records but target is {len(sources)}")

        remaining = [s for s in sources if s["idx"] not in existing_by_source]
        if max_items > 0:
            remaining = remaining[:max_items]
        planned = remaining if commit else remaining[:preview_size]
        print(f"{label}: orig={task['n']} kept={kept_n} target_backfill={len(sources)} "
              f"existing={len(existing)} generating={len(planned)} mode={'commit' if commit else 'preview'}")
        if not planned:
            continue

        review_rows = []
        for n, (source, item) in enumerate(_rewrite_many(task, planned, workers, max_tokens, retries), 1):
            if commit:
                _append_item(label, item)
            review_rows.append({
                "task_type": task["task_type"],
                "source_idx": source["idx"],
                "source_reason": source.get("reason", ""),
                "original": task["data"][source["idx"]],
                "generated": item,
            })
            print(f"  {label}: {n}/{len(planned)} source_idx={source['idx']} | {usage_summary()}",
                  flush=True)

        _write_review(label, review_rows, committed=commit)
        if commit:
            cleaned = sorted(_existing_backfill(label), key=lambda it: int(it["source_idx"]))
            path = os.path.join(BACKFILL_DIR, f"{label}.jsonl")
            with open(path, "w", encoding="utf-8") as f:
                for item in cleaned:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
        else:
            print(f"  preview review -> {_review_path(label)}")

    print("done")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="", help="comma-separated task labels")
    ap.add_argument("--commit", action="store_true", help="write accepted generations to backfill jsonl")
    ap.add_argument("--preview-size", type=int, default=10)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--max-items", type=int, default=-1, help="limit generations per selected task")
    ap.add_argument("--retries", type=int, default=4)
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    args = ap.parse_args()
    tasks_filter = set(s for s in args.tasks.split(",") if s)
    run(tasks_filter, args.commit, args.preview_size, args.workers, args.max_items,
        args.retries, args.max_tokens)


if __name__ == "__main__":
    main()
