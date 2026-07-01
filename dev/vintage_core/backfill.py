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
import csv
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, prompts
from .client import RateLimited, chat_json, cooldown_wait, usage_summary
from .load import load_tasks
from .temporal import annotate, science_anachronisms

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
    """Return (pool, need, kept_n). `pool` is the ordered list of removed items to draw from
    until `need` valid rewrites are collected. For "restore to original N" tasks pool == need
    (no slack — temperature escalation is what gets each source to pass). For boolq the pool is
    the FULL removed set (2,248), shuffled, giving slack to replace any rejected source."""
    records = _audit_records(task["label"])
    if len(records) != task["n"]:
        raise RuntimeError(f"{task['label']} audit is partial: {len(records)}/{task['n']}")
    kept_n = sum(1 for r in records.values() if r["keep"])
    need = _target_count(task["n"], kept_n)
    if need <= 0:
        return [], 0, kept_n

    removed = [records[i] for i in sorted(records) if not records[i]["keep"]]
    if need > len(removed):
        raise RuntimeError(f"{task['label']} needs {need} backfills but only {len(removed)} removed")

    if task["n"] < config.BACKFILL_MAX_N:
        pool = removed                          # == need (draw all; escalate temp to make each pass)
    else:
        pool = list(removed)                    # full pool as slack; deterministic shuffle
        random.Random(BOOLQ_SAMPLE_SEED).shuffle(pool)
    return pool, need, kept_n


def eligible_tasks(tasks_filter=None):
    tasks = []
    for task in load_tasks():
        if tasks_filter and task["label"] not in tasks_filter:
            continue
        pool, need, kept_n = _target_sources(task)
        if need > 0:
            tasks.append((task, pool, need, kept_n))
    return tasks


def _metadata_rows():
    for path in (
        os.path.join(config.OUT_FILTERED, "eval_meta_data.csv"),
        os.path.join(config.EVAL_BUNDLE_DIR, "eval_meta_data.csv"),
    ):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return {r["Eval Task"]: r for r in csv.DictReader(f)}
    raise FileNotFoundError("missing eval_meta_data.csv in filtered or upstream bundle")


# Corrected descriptions for benchmarks whose upstream eval_meta_data.csv text is wrong/misleading.
# arc_challenge's upstream description is copy-pasted from arc_easy ("easy"), which makes the model
# generate items that are too easy — ARC-Challenge is specifically the HARD split.
DESCRIPTION_OVERRIDES = {
    "arc_challenge": ("ARC-Challenge: grade 3-9 science multiple-choice questions that require "
                      "multi-step reasoning and applied understanding, NOT simple fact recall. By "
                      "design these are the hard questions that defeat retrieval and word-co-occurrence "
                      "baselines; distractors are plausible and the correct answer needs reasoning."),
}


def _benchmark_context(task, meta_rows):
    row = meta_rows.get(task["label"], {})
    # Keep this compact: enough for the model to preserve the construct, not the whole CSV.
    return {
        "label": task["label"],
        "category": row.get("Task Category", task.get("verdict", "")),
        "task_type": row.get("Task Type", task["task_type"]),
        "fewshot": row.get("#shots", str(task["num_fewshot"])),
        "random_baseline": row.get("Random baseline", ""),
        "description": DESCRIPTION_OVERRIDES.get(task["label"], row.get("Description", "")).strip(),
    }


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


def _unwrap_generated(generated, keys):
    if not isinstance(generated, dict):
        return generated
    if keys & generated.keys():
        return generated
    queue = [generated]
    seen = set()
    preferred = ("item", "new_item", "replacement", "rewritten_item", "output", "result", "question")
    while queue:
        cur = queue.pop(0)
        ident = id(cur)
        if ident in seen:
            continue
        seen.add(ident)
        for name in preferred:
            nested = cur.get(name)
            if isinstance(nested, dict):
                if keys & nested.keys():
                    return nested
                queue.append(nested)
        for nested in cur.values():
            if isinstance(nested, dict):
                if keys & nested.keys():
                    return nested
                queue.append(nested)
    return generated


def _validate_core(generated, original, task_type):
    if not isinstance(generated, dict):
        raise ValidationError("response is not a JSON object")
    keys = _expected_keys(task_type)
    generated = _unwrap_generated(generated, keys)
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
    if ann["regex_remove"] or ann["modern_terms"]:
        raise ValidationError(
            f"temporal regex hit: years={ann['years_found']} modern_terms={ann['modern_terms']}"
        )
    sci = science_anachronisms(item)
    if sci:
        raise ValidationError(f"post-1930 science concept: {sci}")
    return item


def _rewrite_once(original, task_type, benchmark_context, max_tokens, temperature=0.0):
    return chat_json(
        prompts.backfill_messages(original, task_type, benchmark_context),
        config.REWRITE_MODEL,
        config.REWRITE_BASE_URL,
        temperature=temperature,
        max_tokens=max_tokens,
    )


# On a CONTENT rejection (validation/verify), retrying at temp 0 reproduces the same bad item.
# Escalate temperature so the model actually produces a DIFFERENT candidate that can pass.
_TEMP_SCHEDULE = [0.0, 0.6, 0.9, 1.1]


def _verify(item, task_type):
    """Second-pass judge: reject non-unique answers and post-1930 content in any option."""
    res = chat_json(
        prompts.backfill_verify_messages(item, task_type),
        config.REWRITE_MODEL, config.REWRITE_BASE_URL, temperature=0.0, max_tokens=256,
    )
    if not (isinstance(res, dict) and res.get("ok") is True):
        reason = res.get("reason", "") if isinstance(res, dict) else str(res)[:80]
        raise ValidationError(f"verify rejected: {reason}")


def _rewrite_valid(source, task, benchmark_context, max_tokens, retries):
    original = task["data"][source["idx"]]
    last = None
    content_attempt = 0                       # counts only genuine bad-generation attempts
    while content_attempt < retries:
        temp = _TEMP_SCHEDULE[min(content_attempt, len(_TEMP_SCHEDULE) - 1)]
        try:
            generated = _rewrite_once(original, task["task_type"], benchmark_context,
                                      max_tokens, temperature=temp)
            item = _validate_core(generated, original, task["task_type"])
            _verify(item, task["task_type"])   # reject non-unique / post-1930-in-distractor items
            item["backfilled"] = True
            item["source_idx"] = source["idx"]
            item["source_reason"] = source.get("reason", "")
            item["source_src"] = source.get("src", "")
            return item
        except RateLimited as e:               # throttle, not a bad item: wait, do NOT escalate
            last = e
            time.sleep(min(max(cooldown_wait(), 1.0), 60.0))
        except Exception as e:  # noqa: BLE001  (validation/verify/parse: escalate temperature)
            last = e
            content_attempt += 1
            if content_attempt < retries:
                time.sleep(min(2 ** content_attempt, 8))
    raise RuntimeError(f"{task['label']} source_idx={source['idx']} failed after {retries}: {last}")


def _review_path(label):
    return os.path.join(config.REVIEW_DIR, f"backfill_{label}.md")


def _gold_line(item, task_type):
    if task_type == "multiple_choice":
        gold = item.get("gold")
        choices = item.get("choices", [])
        if isinstance(gold, int) and 0 <= gold < len(choices):
            return f"Gold: [{gold}] {choices[gold]}"
        return f"Gold: {gold}"
    if task_type == "schema":
        gold = item.get("gold")
        options = item.get("context_options", [])
        continuation = item.get("continuation", "")
        if isinstance(gold, int) and 0 <= gold < len(options):
            return f"Gold: [{gold}] {options[gold]} {continuation}".strip()
        return f"Gold: {gold} -> {continuation}".strip()
    if task_type == "language_modeling":
        return f"Gold continuation: {item.get('continuation', '')}"
    return ""


def _write_review(label, rows, committed, benchmark_context, errors=None):
    os.makedirs(config.REVIEW_DIR, exist_ok=True)
    lines = [
        f"# Backfill review: `{label}`",
        "",
        f"Mode: {'commit' if committed else 'preview'}",
        f"Items: {len(rows)}",
        "",
        "## Benchmark context",
        "",
        f"- Category: {benchmark_context.get('category', '')}",
        f"- Task type: {benchmark_context.get('task_type', '')}",
        f"- Few-shot examples: {benchmark_context.get('fewshot', '')}",
        f"- Random baseline: {benchmark_context.get('random_baseline', '')}",
        f"- Description: {benchmark_context.get('description', '')}",
        "",
    ]
    if errors:
        lines += ["## Preview skips", ""]
        for source, err in errors:
            lines.append(f"- source_idx={source['idx']}: {str(err)[:180]}")
        lines.append("")
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
            _gold_line(row["original"], row["task_type"]),
            "",
            "**Generated replacement**",
            "",
            generated,
            "",
            _gold_line(row["generated"], row["task_type"]),
            "",
        ]
    with open(_review_path(label), "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def _append_item(label, item):
    os.makedirs(BACKFILL_DIR, exist_ok=True)
    path = os.path.join(BACKFILL_DIR, f"{label}.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _collect(task, candidates, target, ctx, workers, max_tokens, retries, on_item):
    """Draw from `candidates` (the removed pool) generating valid rewrites until `target` are
    collected or the pool is exhausted. Rejected sources are skipped and REPLACED by the next
    pool item, so the final count stays true to target (given pool slack). Returns (got, skipped)."""
    got, skipped = 0, []
    ci = iter(candidates)
    if workers <= 1:
        for src in ci:
            if got >= target:
                break
            try:
                item = _rewrite_valid(src, task, ctx, max_tokens, retries)
            except Exception as e:  # noqa: BLE001
                skipped.append((src, e))
                print(f"  {task['label']}: skip idx={src['idx']} ({str(e)[:80]})", flush=True)
                continue
            got += 1
            on_item(src, item, got)
        return got, skipped

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {}

        def submit():
            s = next(ci, None)
            if s is not None:
                futs[ex.submit(_rewrite_valid, s, task, ctx, max_tokens, retries)] = s

        for _ in range(workers):
            submit()
        while futs and got < target:
            done = next(as_completed(futs))
            src = futs.pop(done)
            try:
                item = done.result()
            except Exception as e:  # noqa: BLE001
                skipped.append((src, e))
                print(f"  {task['label']}: skip idx={src['idx']} ({str(e)[:80]})", flush=True)
                submit()
                continue
            got += 1
            on_item(src, item, got)
            if got < target:
                submit()
        for f in list(futs):
            f.cancel()
    return got, skipped


def run(tasks_filter, commit, preview_size, workers, max_items, retries, max_tokens):
    targets = eligible_tasks(tasks_filter)
    if not targets:
        print("no backfill-eligible tasks")
        return

    meta_rows = _metadata_rows()
    for task, pool, need, kept_n in targets:
        label = task["label"]
        ctx = _benchmark_context(task, meta_rows)
        existing = _existing_backfill(label)
        existing_by_source = {int(it["source_idx"]): it for it in existing if "source_idx" in it}
        candidates = [s for s in pool if s["idx"] not in existing_by_source]
        target = need - len(existing_by_source)          # how many MORE valid items we need
        if not commit:
            target = min(preview_size, target)
        if max_items > 0:
            target = min(target, max_items)
        print(f"{label}: orig={task['n']} kept={kept_n} need={need} existing={len(existing)} "
              f"pool={len(pool)} generating={target} mode={'commit' if commit else 'preview'}")
        if target <= 0:
            continue

        review_rows = []

        def on_item(src, item, n, _label=label, _task=task, _target=target, _commit=commit):
            review_rows.append({
                "task_type": _task["task_type"], "source_idx": src["idx"],
                "source_reason": src.get("reason", ""), "original": _task["data"][src["idx"]],
                "generated": item,
            })
            if _commit:
                _append_item(_label, item)
            print(f"  {_label}: {n}/{_target} idx={src['idx']} | {usage_summary()}", flush=True)

        got, skipped = _collect(task, candidates, target, ctx, workers, max_tokens, retries, on_item)
        _write_review(label, review_rows, committed=commit, benchmark_context=ctx, errors=skipped)

        if commit:
            cleaned = sorted(_existing_backfill(label), key=lambda it: int(it["source_idx"]))
            with open(os.path.join(BACKFILL_DIR, f"{label}.jsonl"), "w", encoding="utf-8") as f:
                for item in cleaned:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
            flag = "OK" if len(cleaned) >= need else f"SHORT of {need} (pool exhausted)"
            print(f"  {label}: committed {len(cleaned)}/{need} [{flag}]", flush=True)
        else:
            os.makedirs(BACKFILL_DIR, exist_ok=True)
            with open(os.path.join(BACKFILL_DIR, f"{label}.preview.jsonl"), "w", encoding="utf-8") as f:
                for row in review_rows:
                    f.write(json.dumps(row["generated"], ensure_ascii=False) + "\n")
            print(f"  preview {got}/{target} -> {_review_path(label)}", flush=True)

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
