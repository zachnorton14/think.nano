"""Regenerate audited backfill problems without mutating approved previews.

Workflow:
  python -m dev.vintage_core.regenerate stage --workers 2
  python -m dev.vintage_core.regenerate status
  python -m dev.vintage_core.regenerate reject arc_challenge 138 --reason "..."
  python -m dev.vintage_core.regenerate apply

`stage` writes isolated candidates and changed-only review files. `apply` performs an
offline, all-items validation before merging candidates into the authoritative previews.
"""
import argparse
import copy
import hashlib
import json
import os
import tempfile
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import backfill, config, prompts
from .client import RateLimited, Truncated, chat_json, cooldown_wait, usage_summary


MANIFEST_PATH = os.path.join(config.REVIEW_DIR, "backfill_audit.jsonl")
REGEN_DIR = os.path.join(backfill.BACKFILL_DIR, "regeneration")
APPLIED_REPORT = os.path.join(config.REVIEW_DIR, "regeneration_applied.md")
EXPECTED_TOTAL = 72
EXPECTED_STATUS_COUNTS = {"reject": 34, "review": 38}
EXPECTED_MODE_COUNTS = {"fresh": 23, "revise": 49}
VETTED_EXAMPLES = {
    "arc_challenge": [4, 42, 52],
    "openbook_qa": [7, 34, 200],
}


def _candidate_path(label):
    return os.path.join(REGEN_DIR, f"{label}.jsonl")


def _rejection_path(label):
    return os.path.join(REGEN_DIR, f"{label}.rejects.jsonl")


def _review_path(label):
    return os.path.join(config.REVIEW_DIR, f"regeneration_{label}.md")


def _atomic_text(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _read_jsonl(path, description):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise backfill.ValidationError(
                    f"{description} line {line_no} is invalid JSON: {e}"
                ) from e
    return rows


def _load_manifest(enforce_inventory=True):
    rows = _read_jsonl(MANIFEST_PATH, "audit manifest")
    if not rows:
        raise FileNotFoundError(f"missing or empty audit manifest: {MANIFEST_PATH}")
    seen = set()
    entries = []
    for line_no, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise backfill.ValidationError(f"audit manifest line {line_no} is not an object")
        label = row.get("label")
        idx = row.get("source_idx")
        status = row.get("status")
        mode = row.get("mode")
        reason = row.get("reason")
        if not isinstance(label, str) or not label:
            raise backfill.ValidationError(f"audit manifest line {line_no} has invalid label")
        if not isinstance(idx, int) or isinstance(idx, bool):
            raise backfill.ValidationError(f"audit manifest line {line_no} has invalid source_idx")
        if status not in EXPECTED_STATUS_COUNTS:
            raise backfill.ValidationError(f"audit manifest line {line_no} has invalid status")
        if mode not in EXPECTED_MODE_COUNTS:
            raise backfill.ValidationError(f"audit manifest line {line_no} has invalid mode")
        if not isinstance(reason, str) or not reason.strip():
            raise backfill.ValidationError(f"audit manifest line {line_no} has empty reason")
        key = (label, idx)
        if key in seen:
            raise backfill.ValidationError(f"duplicate audit entry: {label} source_idx={idx}")
        seen.add(key)
        entries.append({
            "label": label,
            "source_idx": idx,
            "status": status,
            "reason": reason.strip(),
            "mode": mode,
        })

    if enforce_inventory:
        statuses = Counter(entry["status"] for entry in entries)
        modes = Counter(entry["mode"] for entry in entries)
        if len(entries) != EXPECTED_TOTAL:
            raise backfill.ValidationError(
                f"audit manifest has {len(entries)} items; expected {EXPECTED_TOTAL}"
            )
        if dict(statuses) != EXPECTED_STATUS_COUNTS:
            raise backfill.ValidationError(
                f"audit status counts are {dict(statuses)}; expected {EXPECTED_STATUS_COUNTS}"
            )
        if dict(modes) != EXPECTED_MODE_COUNTS:
            raise backfill.ValidationError(
                f"audit mode counts are {dict(modes)}; expected {EXPECTED_MODE_COUNTS}"
            )
    return sorted(entries, key=lambda entry: (entry["label"], entry["source_idx"]))


def _fingerprint(entry):
    raw = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _task_contexts():
    contexts = {}
    meta_rows = backfill._metadata_rows()
    for task, pool, need, kept_n in backfill.eligible_tasks():
        contexts[task["label"]] = {
            "task": task,
            "pool": pool,
            "need": need,
            "kept_n": kept_n,
            "benchmark": backfill._benchmark_context(task, meta_rows),
            "source_by_idx": {int(source["idx"]): source for source in pool},
        }
    return contexts


def _content_item(item, task_type):
    return {key: copy.deepcopy(item[key]) for key in backfill._expected_keys(task_type)}


def _schema_contract(original, task_type):
    return backfill._schema_contract(original, task_type)


def _preview_by_idx(ctx):
    task = ctx["task"]
    items = backfill._validated_preview(
        task,
        ctx["pool"],
        ctx["need"],
        backfill._load_preview(task["label"]),
        require_complete=True,
    )
    return {int(item["source_idx"]): item for item in items}


def _validate_inventory(entries, contexts, previews):
    problems = []
    for entry in entries:
        label = entry["label"]
        idx = entry["source_idx"]
        if label not in contexts:
            problems.append(f"unknown or ineligible task {label}")
            continue
        if idx not in contexts[label]["source_by_idx"]:
            problems.append(f"{label} source_idx={idx} is not a removed source")
        if idx not in previews[label]:
            problems.append(f"{label} source_idx={idx} is missing from the preview")
        if entry["mode"] == "fresh" and label not in VETTED_EXAMPLES:
            problems.append(f"{label} source_idx={idx} has no vetted fresh examples")
    if problems:
        raise backfill.ValidationError("invalid audit inventory:\n  " + "\n  ".join(problems))


def _load_candidates(label):
    out = {}
    for line_no, row in enumerate(_read_jsonl(_candidate_path(label), f"{label} candidates"), 1):
        if not isinstance(row, dict):
            raise backfill.ValidationError(f"{label} candidate line {line_no} is not an object")
        idx = row.get("source_idx")
        if not isinstance(idx, int) or isinstance(idx, bool):
            raise backfill.ValidationError(f"{label} candidate line {line_no} has invalid source_idx")
        if idx in out:
            raise backfill.ValidationError(f"{label} candidates duplicate source_idx={idx}")
        out[idx] = row
    return out


def _load_candidate_rejections(label):
    out = {}
    for line_no, row in enumerate(
        _read_jsonl(_rejection_path(label), f"{label} candidate rejections"), 1
    ):
        idx = row.get("source_idx") if isinstance(row, dict) else None
        reason = row.get("reason") if isinstance(row, dict) else None
        if not isinstance(idx, int) or isinstance(idx, bool):
            raise backfill.ValidationError(
                f"{label} candidate rejection line {line_no} has invalid source_idx"
            )
        if not isinstance(reason, str) or not reason.strip():
            raise backfill.ValidationError(
                f"{label} candidate rejection line {line_no} has empty reason"
            )
        if idx in out:
            raise backfill.ValidationError(
                f"{label} candidate rejections duplicate source_idx={idx}"
            )
        out[idx] = reason.strip()
    return out


def _write_candidates(label, candidates):
    backfill._atomic_jsonl(
        _candidate_path(label), [candidates[idx] for idx in sorted(candidates)]
    )


def _write_candidate_rejections(label, rejections):
    rows = [{"source_idx": idx, "reason": reason} for idx, reason in sorted(rejections.items())]
    backfill._atomic_jsonl(_rejection_path(label), rows)


def _candidate_item(wrapper):
    item = wrapper.get("candidate") if isinstance(wrapper, dict) else None
    if not isinstance(item, dict):
        raise backfill.ValidationError("candidate wrapper is missing candidate object")
    return item


def _validate_candidate(entry, wrapper, ctx, current, allow_applied=True):
    idx = entry["source_idx"]
    expected = {
        "label": entry["label"],
        "source_idx": idx,
        "status": entry["status"],
        "reason": entry["reason"],
        "mode": entry["mode"],
        "manifest_fingerprint": _fingerprint(entry),
    }
    for key, value in expected.items():
        if wrapper.get(key) != value:
            raise backfill.ValidationError(
                f"{entry['label']} source_idx={idx} candidate has stale {key}"
            )
    item = _candidate_item(wrapper)
    source = ctx["source_by_idx"][idx]
    if item.get("source_idx") != idx or item.get("backfilled") is not True:
        raise backfill.ValidationError(
            f"{entry['label']} source_idx={idx} candidate provenance is invalid"
        )
    if item.get("source_reason", "") != source.get("reason", ""):
        raise backfill.ValidationError(
            f"{entry['label']} source_idx={idx} candidate source_reason is stale"
        )
    if item.get("source_src", "") != source.get("src", ""):
        raise backfill.ValidationError(
            f"{entry['label']} source_idx={idx} candidate source_src is stale"
        )
    backfill._validate_core(item, ctx["task"]["data"][idx], ctx["task"]["task_type"])
    if allow_applied and item == current:
        return "applied"
    previous_revision = wrapper.get("previous_generation_revision")
    current_revision = int(current.get("generation_revision", 0))
    if previous_revision != current_revision:
        raise backfill.ValidationError(
            f"{entry['label']} source_idx={idx} candidate baseline is stale"
        )
    revision = item.get("generation_revision")
    if not isinstance(revision, int) or revision <= current_revision:
        raise backfill.ValidationError(
            f"{entry['label']} source_idx={idx} candidate revision did not increase"
        )
    return "staged"


def _approved_examples(label, previews, task_type):
    ids = VETTED_EXAMPLES.get(label, [])
    missing = [idx for idx in ids if idx not in previews]
    if missing:
        raise backfill.ValidationError(f"{label} is missing vetted examples: {missing}")
    return [_content_item(previews[idx], task_type) for idx in ids]


def _generate_candidate(entry, ctx, current, draft, max_tokens, retries,
                        rejection_feedback="", start_temperature_index=0, revision=1):
    task = ctx["task"]
    idx = entry["source_idx"]
    original = task["data"][idx]
    schema = _schema_contract(original, task["task_type"])
    examples = None
    previous_item = None
    if entry["mode"] == "fresh":
        examples = _approved_examples(entry["label"], _preview_by_idx(ctx), task["task_type"])
    else:
        previous_item = _content_item(draft, task["task_type"])

    attempts = 0
    temperature_index = start_temperature_index
    token_budget = max_tokens
    last = None
    retry_feedback = rejection_feedback
    while attempts < retries:
        temperature = backfill._TEMP_SCHEDULE[
            min(temperature_index, len(backfill._TEMP_SCHEDULE) - 1)
        ]
        messages = prompts.regeneration_messages(
            entry["mode"],
            task["task_type"],
            ctx["benchmark"],
            schema,
            entry["reason"],
            previous_item=previous_item,
            approved_examples=examples,
            retry_feedback=retry_feedback,
        )
        try:
            generated = chat_json(
                messages,
                config.REWRITE_MODEL,
                config.REWRITE_BASE_URL,
                temperature=temperature,
                max_tokens=token_budget,
            )
            item = backfill._validate_core(generated, original, task["task_type"])
            source = ctx["source_by_idx"][idx]
            item["backfilled"] = True
            item["source_idx"] = idx
            item["source_reason"] = source.get("reason", "")
            item["source_src"] = source.get("src", "")
            item["generation_revision"] = revision
            return {
                **entry,
                "manifest_fingerprint": _fingerprint(entry),
                "previous_generation_revision": int(current.get("generation_revision", 0)),
                "candidate": item,
            }
        except Truncated as e:
            last = e
            if token_budget >= backfill.MAX_GENERATION_TOKENS:
                raise RuntimeError(
                    f"{entry['label']} source_idx={idx} truncated at max_tokens={token_budget}"
                ) from e
            token_budget = min(token_budget * 2, backfill.MAX_GENERATION_TOKENS)
        except RateLimited as e:
            last = e
            time.sleep(min(max(cooldown_wait(), 1.0), 60.0))
        except Exception as e:  # noqa: BLE001
            last = e
            attempts += 1
            temperature_index += 1
            token_budget = max_tokens
            retry_feedback = f"{rejection_feedback} Latest validation failure: {e}".strip()
            if attempts < retries:
                time.sleep(min(2 ** attempts, 8))
    raise RuntimeError(
        f"{entry['label']} source_idx={idx} failed after {retries} attempts: {last}"
    )


def _write_review(label, entries, ctx, previews, candidates, rejections, errors=None):
    lines = [
        f"# Regeneration review: `{label}`",
        "",
        f"Items: {len(entries)}",
        "",
        "This file shows only audited replacements. The authoritative preview is unchanged until",
        "`python -m dev.vintage_core.regenerate apply` succeeds.",
        "",
    ]
    errors = errors or {}
    for number, entry in enumerate(entries, 1):
        idx = entry["source_idx"]
        previous = previews[idx]
        wrapper = candidates.get(idx)
        lines += [
            f"## {number}. source_idx={idx}",
            "",
            f"- Audit status: `{entry['status']}`",
            f"- Regeneration mode: `{entry['mode']}`",
            f"- Concern: {entry['reason']}",
        ]
        if idx in rejections:
            lines.append(f"- Candidate rejection: {rejections[idx]}")
        if idx in errors:
            lines.append(f"- Generation error: {errors[idx]}")
        lines += [
            "",
            "**Previous staged item**",
            "",
            prompts.render_item(previous, ctx["task"]["task_type"]).replace("\n", " "),
            "",
            backfill._gold_line(previous, ctx["task"]["task_type"]),
            "",
        ]
        if wrapper:
            candidate = _candidate_item(wrapper)
            lines += [
                "**Regenerated candidate**",
                "",
                prompts.render_item(candidate, ctx["task"]["task_type"]).replace("\n", " "),
                "",
                backfill._gold_line(candidate, ctx["task"]["task_type"]),
                "",
            ]
        else:
            lines += ["**Regenerated candidate**", "", "Not staged.", ""]
    _atomic_text(_review_path(label), "\n".join(lines).rstrip() + "\n")


def _selected_entries(entries, tasks_filter):
    return [entry for entry in entries if not tasks_filter or entry["label"] in tasks_filter]


def stage(tasks_filter=None, workers=2, max_items=-1, retries=4,
          max_tokens=backfill.DEFAULT_MAX_TOKENS):
    entries = _load_manifest()
    contexts = _task_contexts()
    previews = {label: _preview_by_idx(ctx) for label, ctx in contexts.items()}
    _validate_inventory(entries, contexts, previews)
    selected = _selected_entries(entries, tasks_filter or set())
    unknown = sorted((tasks_filter or set()) - {entry["label"] for entry in entries})
    if unknown:
        raise SystemExit(f"no audited items for task(s): {','.join(unknown)}")

    grouped = defaultdict(list)
    for entry in selected:
        grouped[entry["label"]].append(entry)
    remaining = max_items
    failures = []

    for label in sorted(grouped):
        ctx = contexts[label]
        task_entries = sorted(grouped[label], key=lambda entry: entry["source_idx"])
        current = previews[label]
        candidates = _load_candidates(label)
        rejections = _load_candidate_rejections(label)
        allowed = {entry["source_idx"] for entry in task_entries}
        invalid_rejections = sorted(set(rejections) - allowed)
        if invalid_rejections:
            raise backfill.ValidationError(
                f"{label} candidate rejections reference unaudited ids: {invalid_rejections}"
            )

        todo = []
        for entry in task_entries:
            idx = entry["source_idx"]
            wrapper = candidates.get(idx)
            if idx in rejections:
                todo.append(entry)
                continue
            if wrapper:
                try:
                    _validate_candidate(entry, wrapper, ctx, current[idx])
                    continue
                except backfill.ValidationError:
                    pass
            todo.append(entry)
        if remaining == 0:
            todo = []
        elif remaining > 0:
            todo = todo[:remaining]
            remaining -= len(todo)

        print(
            f"{label}: audited={len(task_entries)} staged={len(task_entries) - len(todo)} "
            f"generating={len(todo)}",
            flush=True,
        )
        errors = {}

        def generate(entry):
            idx = entry["source_idx"]
            old_wrapper = candidates.get(idx)
            old_candidate = _candidate_item(old_wrapper) if old_wrapper else None
            draft = old_candidate if idx in rejections and old_candidate else current[idx]
            current_revision = int(current[idx].get("generation_revision", 0))
            candidate_revision = int(old_candidate.get("generation_revision", 0)) if old_candidate else 0
            revision = max(current_revision, candidate_revision) + 1
            return _generate_candidate(
                entry,
                ctx,
                current[idx],
                draft,
                max_tokens,
                retries,
                rejection_feedback=rejections.get(idx, ""),
                start_temperature_index=1 if idx in rejections else 0,
                revision=revision,
            )

        if workers <= 1:
            futures = [(entry, None) for entry in todo]
            for entry, _ in futures:
                idx = entry["source_idx"]
                try:
                    candidates[idx] = generate(entry)
                    rejections.pop(idx, None)
                    _write_candidates(label, candidates)
                    _write_candidate_rejections(label, rejections)
                    print(f"  {label}: idx={idx} | {usage_summary()}", flush=True)
                except Exception as e:  # noqa: BLE001
                    errors[idx] = str(e)
                    failures.append((label, idx, e))
                    print(f"  {label}: ERROR idx={idx} {e}", flush=True)
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_by_entry = {executor.submit(generate, entry): entry for entry in todo}
                for future in as_completed(future_by_entry):
                    entry = future_by_entry[future]
                    idx = entry["source_idx"]
                    try:
                        candidates[idx] = future.result()
                        rejections.pop(idx, None)
                        _write_candidates(label, candidates)
                        _write_candidate_rejections(label, rejections)
                        print(f"  {label}: idx={idx} | {usage_summary()}", flush=True)
                    except Exception as e:  # noqa: BLE001
                        errors[idx] = str(e)
                        failures.append((label, idx, e))
                        print(f"  {label}: ERROR idx={idx} {e}", flush=True)

        _write_review(label, task_entries, ctx, current, candidates, rejections, errors)
        staged = 0
        applied = 0
        for entry in task_entries:
            wrapper = candidates.get(entry["source_idx"])
            if not wrapper:
                continue
            try:
                state = _validate_candidate(entry, wrapper, ctx, current[entry["source_idx"]])
                staged += state == "staged"
                applied += state == "applied"
            except backfill.ValidationError:
                pass
        print(
            f"  candidates staged={staged} applied={applied} pending_rejections={len(rejections)} "
            f"-> {_review_path(label)}",
            flush=True,
        )

    if failures:
        raise SystemExit(
            "REGENERATION STAGING FAILED: "
            + ", ".join(f"{label}:{idx}" for label, idx, _ in failures)
        )
    print("done")


def status(tasks_filter=None):
    entries = _load_manifest()
    contexts = _task_contexts()
    previews = {label: _preview_by_idx(ctx) for label, ctx in contexts.items()}
    _validate_inventory(entries, contexts, previews)
    selected = _selected_entries(entries, tasks_filter or set())
    grouped = defaultdict(list)
    for entry in selected:
        grouped[entry["label"]].append(entry)
    totals = Counter()
    for label in sorted(grouped):
        candidates = _load_candidates(label)
        rejections = _load_candidate_rejections(label)
        counts = Counter()
        for entry in grouped[label]:
            idx = entry["source_idx"]
            if idx in rejections:
                counts["rejected"] += 1
                continue
            wrapper = candidates.get(idx)
            if not wrapper:
                counts["missing"] += 1
                continue
            try:
                counts[_validate_candidate(entry, wrapper, contexts[label], previews[label][idx])] += 1
            except backfill.ValidationError:
                counts["stale"] += 1
        totals.update(counts)
        print(
            f"{label}: total={len(grouped[label])} staged={counts['staged']} "
            f"applied={counts['applied']} rejected={counts['rejected']} "
            f"missing={counts['missing']} stale={counts['stale']}"
        )
    print(
        f"TOTAL: {len(selected)} staged={totals['staged']} applied={totals['applied']} "
        f"rejected={totals['rejected']} missing={totals['missing']} stale={totals['stale']}"
    )
    return totals


def reject_candidate(label, source_idx, reason):
    if not reason.strip():
        raise SystemExit("--reason must be non-empty")
    entries = _load_manifest()
    entry_by_key = {(entry["label"], entry["source_idx"]): entry for entry in entries}
    entry = entry_by_key.get((label, source_idx))
    if not entry:
        raise SystemExit(f"not an audited item: {label} source_idx={source_idx}")
    contexts = _task_contexts()
    current = _preview_by_idx(contexts[label])[source_idx]
    wrapper = _load_candidates(label).get(source_idx)
    if not wrapper:
        raise SystemExit(f"no staged candidate: {label} source_idx={source_idx}")
    state = _validate_candidate(entry, wrapper, contexts[label], current)
    if state == "applied":
        raise SystemExit(f"candidate already applied: {label} source_idx={source_idx}")
    rejections = _load_candidate_rejections(label)
    rejections[source_idx] = reason.strip()
    _write_candidate_rejections(label, rejections)
    print(f"{label}: candidate source_idx={source_idx} rejected; rerun stage")


def _write_applied_report(rows):
    lines = [
        "# Backfill regeneration applied",
        "",
        f"Items replaced: {len(rows)}",
        "",
        "All candidates were deterministically validated and merged offline. Human approval of the",
        "changed-only regeneration review files is the semantic acceptance record.",
        "",
        "| Benchmark | source_idx | Prior revision | New revision | Mode | Audit status |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    for entry, previous, candidate in sorted(
        rows, key=lambda row: (row[0]["label"], row[0]["source_idx"])
    ):
        lines.append(
            f"| {entry['label']} | {entry['source_idx']} | "
            f"{previous.get('generation_revision', 0)} | "
            f"{candidate.get('generation_revision', 0)} | {entry['mode']} | {entry['status']} |"
        )
    _atomic_text(APPLIED_REPORT, "\n".join(lines).rstrip() + "\n")


def apply_candidates():
    entries = _load_manifest()
    contexts = _task_contexts()
    previews = {label: _preview_by_idx(ctx) for label, ctx in contexts.items()}
    _validate_inventory(entries, contexts, previews)
    grouped = defaultdict(list)
    for entry in entries:
        grouped[entry["label"]].append(entry)

    prepared = {}
    applied_rows = []
    errors = []
    for label, task_entries in sorted(grouped.items()):
        ctx = contexts[label]
        current = previews[label]
        candidates = _load_candidates(label)
        rejections = _load_candidate_rejections(label)
        expected_ids = {entry["source_idx"] for entry in task_entries}
        extra = sorted(set(candidates) - expected_ids)
        if extra:
            errors.append(f"{label}: unaudited candidate ids {extra}")
        if rejections:
            errors.append(f"{label}: pending candidate rejections {sorted(rejections)}")
        merged = dict(current)
        for entry in task_entries:
            idx = entry["source_idx"]
            wrapper = candidates.get(idx)
            if not wrapper:
                errors.append(f"{label}: missing candidate source_idx={idx}")
                continue
            try:
                state = _validate_candidate(entry, wrapper, ctx, current[idx])
                candidate = _candidate_item(wrapper)
                previous = current[idx]
                if state == "staged":
                    merged[idx] = candidate
                applied_rows.append((entry, previous, candidate))
            except Exception as e:  # noqa: BLE001
                errors.append(f"{label} source_idx={idx}: {e}")
        if set(merged) != set(current):
            errors.append(f"{label}: merge changed the preview source-id set")
        for idx in set(current) - expected_ids:
            if merged[idx] != current[idx]:
                errors.append(f"{label}: unaudited source_idx={idx} changed")
        final_items = [merged[idx] for idx in sorted(merged)]
        try:
            backfill._validated_preview(
                ctx["task"], ctx["pool"], ctx["need"], final_items, require_complete=True
            )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{label}: merged preview invalid: {e}")
        prepared[label] = final_items

    if errors:
        raise SystemExit("REGENERATION APPLY REFUSED:\n  " + "\n  ".join(errors))
    if len(applied_rows) != EXPECTED_TOTAL:
        raise SystemExit(
            f"REGENERATION APPLY REFUSED: prepared {len(applied_rows)}/{EXPECTED_TOTAL} items"
        )

    for label, final_items in prepared.items():
        backfill._atomic_jsonl(backfill._preview_path(label), final_items)
        ctx = contexts[label]
        rows = [backfill._review_row(ctx["task"], item) for item in final_items]
        backfill._write_review(
            label, rows, committed=False, benchmark_context=ctx["benchmark"]
        )
        print(f"{label}: applied {len(grouped[label])} audited candidates offline")
    _write_applied_report(applied_rows)
    print(f"done -> {APPLIED_REPORT}")


def _task_filter(raw):
    return {label for label in raw.split(",") if label}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    stage_parser = sub.add_parser("stage", help="generate isolated audited candidates")
    stage_parser.add_argument("--tasks", default="", help="comma-separated task labels")
    stage_parser.add_argument("--workers", type=int, default=2)
    stage_parser.add_argument("--max-items", type=int, default=-1)
    stage_parser.add_argument("--retries", type=int, default=4)
    stage_parser.add_argument("--max-tokens", type=int, default=backfill.DEFAULT_MAX_TOKENS)

    status_parser = sub.add_parser("status", help="show candidate progress")
    status_parser.add_argument("--tasks", default="", help="comma-separated task labels")

    reject_parser = sub.add_parser("reject", help="reject one staged candidate")
    reject_parser.add_argument("label")
    reject_parser.add_argument("source_idx", type=int)
    reject_parser.add_argument("--reason", required=True)

    sub.add_parser("apply", help="offline validation and authoritative preview merge")
    args = parser.parse_args()
    if args.command == "stage":
        stage(_task_filter(args.tasks), args.workers, args.max_items, args.retries, args.max_tokens)
    elif args.command == "status":
        status(_task_filter(args.tasks))
    elif args.command == "reject":
        reject_candidate(args.label, args.source_idx, args.reason)
    elif args.command == "apply":
        apply_candidates()


if __name__ == "__main__":
    main()
