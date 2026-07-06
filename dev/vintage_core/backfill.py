"""Stage: generate period-valid replacements for low-N vintage CORE tasks.

Stage a review preview first:
  python -m dev.vintage_core.backfill --preview-size 10

Stage every required item:
  python -m dev.vintage_core.backfill --preview-size 300

Reject an item by deleting its preview line or adding
`{"source_idx": N, "reason": "..."}` to `<label>.rejects.jsonl`, then rerun staging.

Commit after review approval (offline; no model calls):
  python -m dev.vintage_core.backfill --commit

The filter audit is the source of truth. This stage never reruns filtering; it rewrites
all removed items only for benchmarks whose original count was below 1300.
"""
import argparse
import copy
import csv
import json
import os
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config, prompts
from .client import RateLimited, Truncated, chat_json, cooldown_wait, usage_summary
from .load import load_tasks
from .temporal import annotate, science_anachronisms

AUDIT_DIR = os.path.join(config.OUT_FILTERED, "audit")
BACKFILL_DIR = os.path.join(config.OUT_FILTERED, "backfill")
FRESH_EXAMPLE_IDS = {
    "arc_challenge": [4, 42, 52],
    "openbook_qa": [7, 34, 200],
    "winogrande": [61, 116, 462],
}
DEFAULT_MAX_TOKENS = 4096
MAX_GENERATION_TOKENS = 8192


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


def _preview_path(label):
    return os.path.join(BACKFILL_DIR, f"{label}.preview.jsonl")


def _rejects_path(label):
    return os.path.join(BACKFILL_DIR, f"{label}.rejects.jsonl")


def _state_path(label):
    return os.path.join(BACKFILL_DIR, f"{label}.preview.state.json")


def _load_preview(label):
    """Load the reviewable staging file without silently dropping malformed records."""
    path = _preview_path(label)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        out = []
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValidationError(f"{label} preview line {line_no} is invalid JSON: {e}") from e
        return out


def _load_rejections(label):
    path = _rejects_path(label)
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValidationError(f"{label} rejects line {line_no} is invalid JSON: {e}") from e
            idx = record.get("source_idx") if isinstance(record, dict) else None
            if not isinstance(idx, int) or isinstance(idx, bool):
                raise ValidationError(f"{label} rejects line {line_no} has invalid source_idx")
            if idx in out:
                raise ValidationError(f"{label} rejects contains duplicate source_idx={idx}")
            out[idx] = str(record.get("reason", "")).strip()
    return out


def _load_preview_state(label):
    path = _state_path(label)
    if not os.path.exists(path):
        return {"desired_count": 0, "seen_source_idx": [], "revisions": {}}
    with open(path, encoding="utf-8") as f:
        state = json.load(f)
    return {
        "desired_count": max(0, int(state.get("desired_count", 0))),
        "seen_source_idx": [int(idx) for idx in state.get("seen_source_idx", [])],
        "revisions": {str(k): int(v) for k, v in state.get("revisions", {}).items()},
    }


def _atomic_jsonl(path, items):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _atomic_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _review_row(task, item):
    """A review row for an already-generated (seed) item, pairing it with its source original."""
    idx = int(item["source_idx"])
    return {"task_type": task["task_type"], "source_idx": idx,
            "source_reason": item.get("source_reason", ""),
            "original": task["data"][idx], "generated": item}


def _target_count(original_n, kept_n):
    """Only restore tasks whose original benchmark size was below the cutoff."""
    return original_n - kept_n if original_n < config.BACKFILL_MAX_N else 0


def _target_sources(task):
    """Return all removed records for an eligible small benchmark."""
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

    if len(removed) != need:
        raise RuntimeError(f"{task['label']} expected {need} removed records, found {len(removed)}")
    return removed, need, kept_n


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
    # Some compatible JSON endpoints occasionally wrap a single requested object in a one-element
    # array or return a JSON-encoded object string. Normalize only these unambiguous singleton
    # shapes; multiple candidates remain invalid.
    if isinstance(generated, str):
        try:
            generated = json.loads(generated)
        except json.JSONDecodeError:
            pass
    if isinstance(generated, list) and len(generated) == 1:
        generated = generated[0]
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


def _validated_preview(task, pool, need, items, require_complete=False):
    """Validate staged records before reuse or offline commit."""
    source_by_idx = {int(source["idx"]): source for source in pool}
    allowed = set(source_by_idx)
    seen = set()
    validated = []
    for position, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ValidationError(f"{task['label']} preview item {position} is not an object")
        idx = item.get("source_idx")
        if not isinstance(idx, int) or isinstance(idx, bool) or idx not in allowed:
            raise ValidationError(f"{task['label']} preview item {position} has invalid source_idx={idx}")
        if idx in seen:
            raise ValidationError(f"{task['label']} preview contains duplicate source_idx={idx}")
        if item.get("backfilled") is not True:
            raise ValidationError(f"{task['label']} source_idx={idx} is missing backfilled=true")
        source = source_by_idx[idx]
        if item.get("source_reason", "") != source.get("reason", ""):
            raise ValidationError(f"{task['label']} source_idx={idx} has stale source_reason")
        if item.get("source_src", "") != source.get("src", ""):
            raise ValidationError(f"{task['label']} source_idx={idx} has stale source_src")
        _validate_core(item, task["data"][idx], task["task_type"])
        seen.add(idx)
        validated.append(item)
    if len(validated) > need:
        raise ValidationError(f"{task['label']} preview has {len(validated)} items; target is {need}")
    if require_complete and seen != allowed:
        missing = sorted(allowed - seen)
        extra = sorted(seen - allowed)
        raise ValidationError(
            f"{task['label']} preview is incomplete: {len(validated)}/{need}; "
            f"missing={missing[:12]} extra={extra[:12]}"
        )
    return validated


def _rewrite_once(original, task_type, benchmark_context, max_tokens, temperature=0.0,
                  rejection_feedback=""):
    return chat_json(
        prompts.backfill_messages(original, task_type, benchmark_context, rejection_feedback),
        config.REWRITE_MODEL,
        config.REWRITE_BASE_URL,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _schema_contract(original, task_type):
    schema = {"required_keys": sorted(_expected_keys(task_type))}
    if task_type == "multiple_choice":
        schema["choice_count"] = len(original["choices"])
        if _choice_list_is_fixed(original["choices"]):
            schema["fixed_choices"] = copy.deepcopy(original["choices"])
    elif task_type == "schema":
        schema["context_option_count"] = len(original["context_options"])
    return schema


def _fresh_once(original, task_type, benchmark_context, concern, approved_examples, max_tokens,
                temperature=0.0, rejection_feedback=""):
    """Generate without exposing a reconciled post-1930 source item to the model."""
    messages = prompts.regeneration_messages(
        "fresh",
        task_type,
        benchmark_context,
        _schema_contract(original, task_type),
        concern,
        approved_examples=approved_examples,
        retry_feedback=rejection_feedback,
    )
    return chat_json(
        messages,
        config.REWRITE_MODEL,
        config.REWRITE_BASE_URL,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _fresh_examples(task):
    ids = FRESH_EXAMPLE_IDS.get(task["label"], [])
    previews = {int(item["source_idx"]): item for item in _load_preview(task["label"])}
    missing = [idx for idx in ids if idx not in previews]
    if missing:
        raise ValidationError(f"{task['label']} is missing vetted fresh examples: {missing}")
    keys = _expected_keys(task["task_type"])
    return [{key: copy.deepcopy(previews[idx][key]) for key in keys} for idx in ids]


# On a content rejection, retrying at temperature 0 tends to reproduce the same bad item.
# Escalate temperature so the model actually produces a DIFFERENT candidate that can pass.
_TEMP_SCHEDULE = [0.0, 0.6, 0.9, 1.1]


def _rewrite_valid(source, task, benchmark_context, max_tokens, retries,
                   rejection_feedback="", start_temperature_index=0, revision=1):
    original = task["data"][source["idx"]]
    last = None
    attempts = 0
    # GLM-5.2 can deterministically emit JSON ``null`` for schema-only fresh prompts at zero
    # temperature. Reconciled fresh-topic items start at the proven 0.6 revision temperature.
    temperature_index = max(start_temperature_index, 1) if source.get("src") == "policy" \
        else start_temperature_index
    token_budget = max_tokens
    retry_feedback = rejection_feedback
    approved_examples = _fresh_examples(task) if source.get("src") == "policy" else []
    while attempts < retries:
        temp = _TEMP_SCHEDULE[min(temperature_index, len(_TEMP_SCHEDULE) - 1)]
        generated = None
        try:
            if source.get("src") == "policy":
                generated = _fresh_once(
                    original,
                    task["task_type"],
                    benchmark_context,
                    source.get("reason", "current temporal policy conflict"),
                    approved_examples,
                    token_budget,
                    temperature=temp,
                    rejection_feedback=retry_feedback,
                )
            else:
                generated = _rewrite_once(original, task["task_type"], benchmark_context,
                                          token_budget, temperature=temp,
                                          rejection_feedback=rejection_feedback)
            item = _validate_core(generated, original, task["task_type"])
            item["backfilled"] = True
            item["source_idx"] = source["idx"]
            item["source_reason"] = source.get("reason", "")
            item["source_src"] = source.get("src", "")
            item["generation_revision"] = revision
            return item
        except Truncated as e:
            last = e
            if token_budget >= MAX_GENERATION_TOKENS:
                raise RuntimeError(
                    f"{task['label']} source_idx={source['idx']} truncated at "
                    f"max_tokens={token_budget}"
                ) from e
            token_budget = min(token_budget * 2, MAX_GENERATION_TOKENS)
        except RateLimited as e:               # throttle, not a bad item: wait, do NOT escalate
            last = e
            time.sleep(min(max(cooldown_wait(), 1.0), 60.0))
        except Exception as e:  # noqa: BLE001  (validation/parse: generate a different candidate)
            last = e
            attempts += 1
            temperature_index += 1
            token_budget = max_tokens
            # A missing/non-JSON response is a transport/format failure, not useful semantic
            # feedback. Passing it back can make GLM repeat JSON ``null``. Only feed back errors
            # from an actual candidate object.
            retry_feedback = rejection_feedback if generated is None else (
                f"{rejection_feedback} Latest validation failure: {e}"
            ).strip()
            if attempts < retries:
                time.sleep(min(2 ** attempts, 8))
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


def _atomic_copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(dst) + ".", dir=os.path.dirname(dst))
    try:
        with open(src, "rb") as source, os.fdopen(fd, "wb") as target:
            shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
        os.replace(tmp, dst)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _collect(task, candidates, target, ctx, workers, max_tokens, retries, on_item,
             generation_options=None):
    """Generate up to `target` valid rewrites from the supplied source records."""
    got, skipped = 0, []
    generation_options = generation_options or {}

    def rewrite(source):
        options = generation_options.get(int(source["idx"]), {})
        return _rewrite_valid(source, task, ctx, max_tokens, retries, **options)

    ci = iter(candidates)
    if workers <= 1:
        for src in ci:
            if got >= target:
                break
            try:
                item = rewrite(src)
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
                futs[ex.submit(rewrite, s)] = s

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


def _commit_previews(targets, meta_rows):
    """Validate every selected preview first, then copy them without any API calls."""
    prepared = []
    errors = []
    for task, pool, need, _ in targets:
        label = task["label"]
        try:
            rejects = _load_rejections(label)
            if rejects:
                raise ValidationError(
                    f"{label} still has {len(rejects)} pending rejection(s): {sorted(rejects)[:12]}"
                )
            source = _preview_path(label)
            if not os.path.exists(source):
                raise ValidationError(f"{label} has no staged preview: {source}")
            items = _validated_preview(task, pool, need, _load_preview(label), require_complete=True)
            prepared.append((task, need, source, items, _benchmark_context(task, meta_rows)))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{label}: {e}")
    if errors:
        raise SystemExit("BACKFILL COMMIT REFUSED:\n  " + "\n  ".join(errors))

    for task, need, source, items, ctx in prepared:
        label = task["label"]
        destination = os.path.join(BACKFILL_DIR, f"{label}.jsonl")
        _atomic_copy(source, destination)
        rows = [_review_row(task, item) for item in sorted(items, key=lambda it: it["source_idx"])]
        _write_review(label, rows, committed=True, benchmark_context=ctx)
        print(f"{label}: committed reviewed preview {len(items)}/{need} -> {destination}")


def _stage_task(task, pool, need, kept_n, ctx, preview_size, workers, max_items,
                retries, max_tokens):
    label = task["label"]
    staged = _validated_preview(task, pool, need, _load_preview(label))
    staged_by_idx = {int(item["source_idx"]): item for item in staged}
    rejections = _load_rejections(label)
    allowed = {int(source["idx"]) for source in pool}
    invalid_rejects = sorted(set(rejections) - allowed)
    if invalid_rejects:
        raise ValidationError(f"{label} rejects invalid source_idx values: {invalid_rejects[:12]}")

    state = _load_preview_state(label)
    seen = set(state["seen_source_idx"])
    revisions = dict(state["revisions"])
    for idx, item in staged_by_idx.items():
        revisions.setdefault(str(idx), int(item.get("generation_revision", 1)))
    for idx in rejections:
        staged_by_idx.pop(idx, None)

    requested = min(preview_size, need)
    desired = min(need, max(requested, state["desired_count"], len(staged_by_idx) + len(rejections)))
    missing = [source for source in pool if source["idx"] not in staged_by_idx]
    rejected_ids = set(rejections) | (seen - set(staged_by_idx))
    mandatory = [source for source in missing if source["idx"] in rejected_ids]
    fresh = [source for source in missing if source["idx"] not in rejected_ids]
    target = max(0, desired - len(staged_by_idx))
    if max_items > 0:
        target = min(target, max_items)
    mandatory = mandatory[:target]
    fresh_target = max(0, target - len(mandatory))
    fresh = fresh[:fresh_target]
    candidates = mandatory + fresh

    options = {}
    for source in candidates:
        idx = int(source["idx"])
        was_rejected = idx in rejected_ids
        feedback = rejections.get(idx, "")
        if was_rejected and not feedback:
            feedback = "The previous staged replacement was rejected during human review."
        options[idx] = {
            "rejection_feedback": feedback,
            "start_temperature_index": 1 if was_rejected else 0,
            "revision": int(revisions.get(str(idx), 0)) + 1,
        }

    print(f"{label}: orig={task['n']} kept={kept_n} need={need} staged={len(staged_by_idx)} "
          f"desired={desired} generating={len(candidates)} mode=preview")
    generated = {}

    def on_item(source, item, n):
        idx = int(source["idx"])
        generated[idx] = item
        revisions[str(idx)] = int(item.get("generation_revision", 1))
        print(f"  {label}: {n}/{len(candidates)} idx={idx} | {usage_summary()}", flush=True)

    got, skipped = (0, [])
    if candidates:
        got, skipped = _collect(
            task, candidates, len(candidates), ctx, workers, max_tokens, retries, on_item,
            generation_options=options,
        )
    staged_by_idx.update(generated)
    final_items = [staged_by_idx[idx] for idx in sorted(staged_by_idx)]
    _validated_preview(task, pool, need, final_items)
    _atomic_jsonl(_preview_path(label), final_items)

    unresolved_rejections = [
        {"source_idx": idx, "reason": reason}
        for idx, reason in sorted(rejections.items()) if idx not in generated
    ]
    _atomic_jsonl(_rejects_path(label), unresolved_rejections)
    failed_ids = {int(source["idx"]) for source, _ in skipped}
    for idx in failed_ids:
        revisions[str(idx)] = max(
            int(revisions.get(str(idx), 0)), int(options.get(idx, {}).get("revision", 1))
        )
    state["desired_count"] = desired
    state["seen_source_idx"] = sorted(seen | set(staged_by_idx) | failed_ids)
    state["revisions"] = revisions
    _atomic_json(_state_path(label), state)

    rows = [_review_row(task, item) for item in final_items]
    _write_review(label, rows, committed=False, benchmark_context=ctx, errors=skipped)
    expected = len(staged) - len(set(rejections) & {it["source_idx"] for it in staged}) + len(candidates)
    complete = len(final_items) >= expected and got == len(candidates)
    print(f"  preview staged={len(final_items)}/{desired} generated={got}/{len(candidates)} "
          f"-> {_review_path(label)}", flush=True)
    return complete, len(final_items), desired


def run(tasks_filter, commit, preview_size, workers, max_items, retries, max_tokens):
    targets = eligible_tasks(tasks_filter)
    if not targets:
        print("no backfill-eligible tasks")
        return

    meta_rows = _metadata_rows()
    if commit:
        _commit_previews(targets, meta_rows)
        print("done")
        return

    short = []
    for task, pool, need, kept_n in targets:
        ctx = _benchmark_context(task, meta_rows)
        try:
            complete, got, desired = _stage_task(
                task, pool, need, kept_n, ctx, preview_size, workers, max_items,
                retries, max_tokens,
            )
            if not complete:
                short.append((task["label"], got, desired))
        except Exception as e:  # noqa: BLE001
            short.append((task["label"], 0, min(preview_size, need)))
            print(f"{task['label']}: ERROR {e}", flush=True)
    if short:
        raise SystemExit("BACKFILL STAGING SHORT: "
                         + ", ".join(f"{label} {got}/{wanted}" for label, got, wanted in short))
    print("done")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="", help="comma-separated task labels")
    ap.add_argument("--commit", action="store_true",
                    help="offline: validate and copy complete reviewed previews; never calls the API")
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
