"""Stage implementations for the Vintage GSM8K adaptation pipeline."""

from __future__ import annotations

import json
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import datetime, timezone

from .client import (
    APIError,
    FreeUsageLimitError,
    OpenCodeClient,
    RateLimitError,
    RegionOptInError,
)
from .config import (
    CHAT_ENDPOINT,
    DATASET_ID,
    DATASET_SUBSET,
    EXPECTED_COUNTS,
    JUDGE_ENDPOINT,
    JUDGE_MODEL,
    JUDGE_PROMPT_VERSION,
    NORMALIZATION_VERSION,
    PREFILTER_VERSION,
    RESPONSES_ENDPOINT,
    REWRITE_FREE_ENDPOINT,
    REWRITE_FREE_MODEL,
    REWRITE_MODEL,
    REWRITE_PAID_ENDPOINT,
    REWRITE_PAID_MODEL,
    REWRITE_PROMPT_VERSION,
    SOLVER_MODEL,
    SOLVER_PROMPT_VERSION,
    PipelinePaths,
    canonical_model_family,
)
from .data import (
    ANNOTATION_RE,
    answers_equal,
    append_jsonl,
    atomic_write_json,
    atomic_write_jsonl,
    cross_split_duplicates,
    extract_final_answer,
    final_answer_count,
    parse_calculator_annotations,
    post_cutoff_years,
    read_jsonl,
    read_latest_by_id,
    stable_hash,
    validate_candidate,
)
from .prompts import (
    JUDGE_SYSTEM_PROMPT,
    REWRITE_SYSTEM_PROMPT,
    SOLVER_SYSTEM_PROMPT,
    judge_user_payload,
    rewrite_user_payload,
)
from .prefilter import prefilter as run_prefilter


SPLITS = ("train", "test")
VALID_JUDGE_ACTIONS = {"keep", "rewrite", "review"}
VALID_REVIEW_DECISIONS = {"keep", "rewrite", "manual"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prompt_manifest() -> dict:
    return {
        "judge": {"version": JUDGE_PROMPT_VERSION, "hash": stable_hash(JUDGE_SYSTEM_PROMPT)},
        "rewrite": {"version": REWRITE_PROMPT_VERSION, "hash": stable_hash(REWRITE_SYSTEM_PROMPT)},
        "solver": {"version": SOLVER_PROMPT_VERSION, "hash": stable_hash(SOLVER_SYSTEM_PROMPT)},
    }


def prepare(paths: PipelinePaths, revision: str = "main") -> dict:
    """Resolve and snapshot official GSM8K without ever replacing an existing snapshot."""
    if paths.manifest.exists():
        manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
        for split, expected in EXPECTED_COUNTS.items():
            rows = read_jsonl(paths.source(split))
            if len(rows) != expected:
                raise RuntimeError(
                    f"Existing source snapshot is incomplete ({split}: {len(rows)}/{expected}); "
                    "use a new --artifact-root rather than overwriting it"
                )
        if manifest.get("normalization_version") != NORMALIZATION_VERSION:
            raise RuntimeError("Existing snapshot uses another normalization version; use a new --artifact-root")
        return manifest

    if any(paths.source(split).exists() for split in SPLITS):
        raise RuntimeError("Source files exist without a manifest; use a new --artifact-root")

    try:
        from datasets import load_dataset
        from huggingface_hub import HfApi
    except ImportError as exc:
        raise RuntimeError("Dataset dependencies are missing; run `uv sync --group dev`") from exc

    info = HfApi().dataset_info(DATASET_ID, revision=revision)
    resolved_revision = info.sha
    split_fingerprints: dict[str, str] = {}
    staged: dict[str, list[dict]] = {}
    for split, expected in EXPECTED_COUNTS.items():
        dataset = load_dataset(DATASET_ID, DATASET_SUBSET, split=split, revision=resolved_revision)
        if len(dataset) != expected:
            raise RuntimeError(f"Official {split} count changed: expected {expected}, got {len(dataset)}")
        split_fingerprints[split] = dataset._fingerprint
        rows = []
        for index, source in enumerate(dataset):
            question = source["question"]
            raw_answer = source["answer"]
            calculations = parse_calculator_annotations(raw_answer)
            invalid = [item for item in calculations if not item["valid"]]
            if invalid:
                raise RuntimeError(f"Invalid official calculator annotation at {split}[{index}]: {invalid}")
            answer = ANNOTATION_RE.sub("", raw_answer)
            if ANNOTATION_RE.search(answer) or final_answer_count(answer) != 1 or extract_final_answer(answer) is None:
                raise RuntimeError(f"Official answer failed normalization checks at {split}[{index}]")
            row_id = f"gsm8k-{DATASET_SUBSET}-{split}-{index:06d}"
            source_hash = stable_hash(
                {
                    "id": row_id,
                    "question": question,
                    "raw_answer": raw_answer,
                    "normalization_version": NORMALIZATION_VERSION,
                }
            )
            rows.append(
                {
                    "id": row_id,
                    "split": split,
                    "index": index,
                    "question": question,
                    "answer": answer,
                    "raw_answer": raw_answer,
                    "calculations": calculations,
                    "source_hash": source_hash,
                }
            )
        staged[split] = rows

    manifest = {
        "created_at": utc_now(),
        "dataset": DATASET_ID,
        "subset": DATASET_SUBSET,
        "requested_revision": revision,
        "resolved_revision": resolved_revision,
        "dataset_fingerprint": stable_hash(split_fingerprints),
        "dataset_fingerprints": split_fingerprints,
        "split_counts": EXPECTED_COUNTS,
        "normalization_version": NORMALIZATION_VERSION,
        "prefilter_version": PREFILTER_VERSION,
        "prompts": _prompt_manifest(),
    }
    for split in SPLITS:
        atomic_write_jsonl(paths.source(split), staged[split])
    atomic_write_json(paths.manifest, manifest)
    return manifest


def _validate_judge_response(value: object, expected_ids: list[str]) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("judge output must be a JSON array")
    expected, seen = set(expected_ids), set()
    normalized = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("every judge output item must be an object")
        row_id, action, reason = item.get("id"), item.get("action"), item.get("reason")
        if row_id not in expected:
            raise ValueError(f"judge returned unknown ID {row_id!r}")
        if row_id in seen:
            raise ValueError(f"judge returned duplicate ID {row_id!r}")
        if action not in VALID_JUDGE_ACTIONS:
            raise ValueError(f"invalid action for {row_id}: {action!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"missing reason for {row_id}")
        seen.add(row_id)
        normalized.append({"id": row_id, "action": action, "reason": reason.strip()})
    missing = expected - seen
    if missing:
        raise ValueError(f"judge omitted IDs: {sorted(missing)}")
    order = {row_id: index for index, row_id in enumerate(expected_ids)}
    return sorted(normalized, key=lambda item: order[item["id"]])


def _call_record(stage: str, ids: list[str], metadata: dict | None, error: str | None = None) -> dict:
    return {
        "timestamp": utc_now(),
        "stage": stage,
        "ids": ids,
        "status": "error" if error else "ok",
        "error": error,
        **(metadata or {}),
    }


def _judge_with_recovery(
    rows: list[dict], client: OpenCodeClient, max_tokens: int
) -> tuple[list[dict], list[dict]]:
    calls: list[dict] = []
    last_error = "unknown judge failure"
    for _ in range(2):
        started = time.monotonic()
        metadata = None
        try:
            value, metadata = client.chat_json(
                model=JUDGE_MODEL,
                system=JUDGE_SYSTEM_PROMPT,
                user=judge_user_payload(rows),
                max_tokens=max_tokens,
                endpoint=JUDGE_ENDPOINT,
            )
            verdicts = _validate_judge_response(value, [row["id"] for row in rows])
            calls.append(_call_record("judge", [row["id"] for row in rows], metadata))
            by_id = {row["id"]: row for row in rows}
            return [
                {
                    **verdict,
                    "split": by_id[verdict["id"]]["split"],
                    "index": by_id[verdict["id"]]["index"],
                    "source_hash": by_id[verdict["id"]]["source_hash"],
                    "prompt_version": JUDGE_PROMPT_VERSION,
                    "model": JUDGE_MODEL,
                    "endpoint": JUDGE_ENDPOINT,
                    "completed_at": utc_now(),
                }
                for verdict in verdicts
            ], calls
        except APIError as exc:
            # HTTP/API failures are resumable error records. Bisection cannot repair them and
            # would amplify a single outage or access denial into hundreds of pointless calls.
            last_error = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, FreeUsageLimitError):
                error_type = "free_usage_limit"
            elif isinstance(exc, RateLimitError):
                error_type = "rate_limit"
            elif isinstance(exc, RegionOptInError):
                error_type = "region_opt_in"
            else:
                error_type = "api"
            call = _call_record(
                "judge",
                [row["id"] for row in rows],
                metadata or {
                    "endpoint": JUDGE_ENDPOINT,
                    "model": JUDGE_MODEL,
                    "latency_seconds": round(time.monotonic() - started, 6),
                },
                last_error,
            )
            call["error_type"] = error_type
            calls.append(call)
            return [
                {
                    "id": row["id"],
                    "split": row["split"],
                    "index": row["index"],
                    "action": "error",
                    "reason": last_error,
                    "source_hash": row["source_hash"],
                    "prompt_version": JUDGE_PROMPT_VERSION,
                    "model": JUDGE_MODEL,
                    "endpoint": JUDGE_ENDPOINT,
                    "error_type": error_type,
                    "completed_at": utc_now(),
                }
                for row in rows
            ], calls
        except Exception as exc:  # malformed output: retry once, then bisect to isolate bad rows
            last_error = f"{type(exc).__name__}: {exc}"
            calls.append(
                _call_record(
                    "judge",
                    [row["id"] for row in rows],
                    metadata or {
                        "endpoint": JUDGE_ENDPOINT,
                        "model": JUDGE_MODEL,
                        "latency_seconds": round(time.monotonic() - started, 6),
                    },
                    last_error,
                )
            )
    if len(rows) > 1:
        middle = len(rows) // 2
        left, left_calls = _judge_with_recovery(rows[:middle], client, max_tokens)
        right, right_calls = _judge_with_recovery(rows[middle:], client, max_tokens)
        return left + right, calls + left_calls + right_calls
    row = rows[0]
    return [
        {
            "id": row["id"],
            "split": row["split"],
            "index": row["index"],
            "action": "error",
            "reason": last_error,
            "source_hash": row["source_hash"],
            "prompt_version": JUDGE_PROMPT_VERSION,
            "model": JUDGE_MODEL,
            "endpoint": JUDGE_ENDPOINT,
            "completed_at": utc_now(),
        }
    ], calls


def _strided_sample(rows: list[dict], count: int | None) -> list[dict]:
    if count is None or count >= len(rows):
        return rows
    if count <= 0:
        return []
    if count == 1:
        return [rows[0]]
    indices = [round(i * (len(rows) - 1) / (count - 1)) for i in range(count)]
    return [rows[index] for index in indices]


def _chunks(rows: list[dict], size: int) -> list[list[dict]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def judge(
    paths: PipelinePaths,
    *,
    revision: str = "main",
    sample_per_split: int | None = None,
    batch_size: int = 32,
    workers: int = 8,
    max_tokens: int = 8192,
    max_items: int | None = None,
    client: OpenCodeClient | None = None,
) -> dict:
    if batch_size < 1 or workers < 1 or (max_items is not None and max_items < 1):
        raise ValueError("batch size and worker count must be positive")
    prepare(paths, revision=revision)
    if not paths.regex_manifest.exists():
        run_prefilter(paths)
    client = client or OpenCodeClient()
    pending_rows: list[dict] = []
    for split in SPLITS:
        rows = read_jsonl(paths.source(split))
        latest = read_latest_by_id(paths.judge(split))
        selected = _strided_sample(rows, sample_per_split)
        pending = [
            row
            for row in selected
            if not (
                (cached := latest.get(row["id"]))
                and cached.get("action") in VALID_JUDGE_ACTIONS
                and cached.get("source_hash") == row["source_hash"]
                and cached.get("prompt_version") == JUDGE_PROMPT_VERSION
                and canonical_model_family(cached.get("model"))
                == canonical_model_family(JUDGE_MODEL)
            )
        ]
        pending_rows.extend(pending)

    if max_items is not None:
        pending_rows = pending_rows[:max_items]
    pending_batches = _chunks(pending_rows, batch_size)

    halt_reason = None
    if pending_batches:
        batches = iter(pending_batches)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}

            def submit_next() -> bool:
                try:
                    batch = next(batches)
                except StopIteration:
                    return False
                futures[pool.submit(_judge_with_recovery, batch, client, max_tokens)] = batch
                return True

            for _ in range(min(workers, len(pending_batches))):
                submit_next()

            while futures:
                completed, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in completed:
                    futures.pop(future)
                    verdicts, calls = future.result()
                    by_split: dict[str, list[dict]] = {split: [] for split in SPLITS}
                    for verdict in verdicts:
                        by_split[verdict["split"]].append(verdict)
                    for split, records in by_split.items():
                        if records:
                            append_jsonl(paths.judge(split), records)
                    append_jsonl(paths.calls, calls)
                    stop_errors = {
                        row.get("error_type")
                        for row in verdicts
                        if row.get("error_type") in {"free_usage_limit", "rate_limit", "region_opt_in"}
                    }
                    if stop_errors:
                        halt_reason = sorted(stop_errors)[0]

                if halt_reason:
                    for future in list(futures):
                        if future.cancel():
                            futures.pop(future)
                else:
                    for _ in completed:
                        submit_next()
    report(paths)
    result = status(paths)
    if halt_reason:
        result["halted"] = halt_reason
    return result


def _current_judges(paths: PipelinePaths) -> dict[str, dict]:
    current: dict[str, dict] = {}
    for split in SPLITS:
        sources = {row["id"]: row for row in read_jsonl(paths.source(split))}
        for row_id, verdict in read_latest_by_id(paths.judge(split)).items():
            source = sources.get(row_id)
            if (
                source
                and verdict.get("source_hash") == source["source_hash"]
                and verdict.get("prompt_version") == JUDGE_PROMPT_VERSION
                and canonical_model_family(verdict.get("model"))
                == canonical_model_family(JUDGE_MODEL)
            ):
                current[row_id] = verdict
    return current


def report(paths: PipelinePaths) -> dict:
    paths.review_dir.mkdir(parents=True, exist_ok=True)
    sources = {
        row["id"]: row for split in SPLITS for row in read_jsonl(paths.source(split))
    }
    judges = _current_judges(paths)
    old_decisions = read_latest_by_id(paths.decisions)
    flagged = [
        verdict
        for verdict in judges.values()
        if verdict.get("action") in {"rewrite", "review", "error"}
    ]
    flagged.sort(key=lambda row: (SPLITS.index(row["split"]), row["index"]))
    decisions = []
    for verdict in flagged:
        source = sources[verdict["id"]]
        existing = old_decisions.get(verdict["id"], {})
        preserve_existing = (
            existing.get("source_hash") == source["source_hash"]
            and existing.get("judge_prompt_version") == JUDGE_PROMPT_VERSION
        )
        if not preserve_existing:
            existing = {}
        default_mode = "date" if post_cutoff_years(source["question"] + "\n" + source["answer"]) else "surface"
        decisions.append(
            {
                "id": verdict["id"],
                "split": verdict["split"],
                "index": verdict["index"],
                "judge_action": verdict["action"],
                "judge_reason": verdict["reason"],
                "judge_prompt_version": JUDGE_PROMPT_VERSION,
                "source_hash": source["source_hash"],
                "decision": existing.get("decision"),
                "reason": existing.get("reason", ""),
                "mode": existing.get("mode", default_mode),
                **{
                    key: existing[key]
                    for key in ("question", "answer", "calculations")
                    if key in existing
                },
            }
        )
    atomic_write_jsonl(paths.decisions, decisions)

    lines = [
        "# Vintage GSM8K judge review",
        "",
        f"Generated: {utc_now()}",
        "",
        "Edit `decisions.jsonl`. Set `decision` to `keep`, `rewrite`, or `manual`, and add a reason.",
        "For `manual`, also provide `question`, `answer`, and `calculations`. Do not run rewrite until these choices are reviewed.",
        "",
        f"Flagged rows: {len(flagged)}",
        "",
    ]
    for verdict in flagged:
        source = sources[verdict["id"]]
        lines.extend(
            [
                f"## {verdict['id']} — {verdict['action']}",
                "",
                f"Reason: {verdict['reason']}",
                "",
                "Question:",
                "",
                source["question"],
                "",
                "Solution:",
                "",
                "```text",
                source["answer"],
                "```",
                "",
            ]
        )
    paths.review_markdown.write_text("\n".join(lines), encoding="utf-8")
    return {"flagged": len(flagged), "decisions_file": str(paths.decisions)}


def _load_complete_decisions(paths: PipelinePaths, judges: dict[str, dict]) -> dict[str, dict]:
    decisions = read_latest_by_id(paths.decisions)
    flagged_ids = {
        row_id for row_id, verdict in judges.items() if verdict.get("action") in {"rewrite", "review", "error"}
    }
    missing = sorted(row_id for row_id in flagged_ids if row_id not in decisions)
    invalid = sorted(
        row_id
        for row_id in flagged_ids
        if row_id in decisions
        and (
            decisions[row_id].get("decision") not in VALID_REVIEW_DECISIONS
            or not isinstance(decisions[row_id].get("reason"), str)
            or not decisions[row_id].get("reason", "").strip()
            or decisions[row_id].get("judge_prompt_version") != JUDGE_PROMPT_VERSION
            or decisions[row_id].get("source_hash") != judges[row_id].get("source_hash")
        )
    )
    if missing or invalid:
        raise RuntimeError(
            f"Review gate is incomplete: {len(missing)} missing and {len(invalid)} undecided/invalid rows. "
            f"Edit {paths.decisions}"
        )
    return {row_id: decisions[row_id] for row_id in flagged_ids}


def _rewrite_one(
    source: dict,
    decision: dict,
    client: OpenCodeClient,
    max_attempts: int,
    model: str = REWRITE_MODEL,
    endpoint: str = CHAT_ENDPOINT,
) -> tuple[list[dict], list[dict]]:
    attempts: list[dict] = []
    calls: list[dict] = []
    feedback = ""
    decision_hash = stable_hash(
        {"decision": decision.get("decision"), "reason": decision.get("reason"), "mode": decision.get("mode")}
    )
    for attempt in range(1, max_attempts + 1):
        started = time.monotonic()
        metadata = None
        error_type = None
        try:
            candidate, metadata = client.chat_json(
                model=model,
                system=REWRITE_SYSTEM_PROMPT,
                user=rewrite_user_payload(
                    source, decision.get("reason") or decision.get("judge_reason", ""), decision["mode"], feedback
                ),
                max_tokens=8192,
                temperature=0.2,
                endpoint=endpoint,
            )
            calls.append(_call_record("rewrite", [source["id"]], metadata))
            if not isinstance(candidate, dict):
                errors = ["rewrite output must be a JSON object"]
                candidate = {}
            else:
                errors = validate_candidate(source, candidate, decision["mode"])
        except Exception as exc:
            errors = [f"{type(exc).__name__}: {exc}"]
            candidate = {}
            if isinstance(exc, FreeUsageLimitError):
                error_type = "free_usage_limit"
            elif isinstance(exc, RateLimitError):
                error_type = "rate_limit"
            elif isinstance(exc, RegionOptInError):
                error_type = "region_opt_in"
            elif isinstance(exc, APIError):
                error_type = "api"
            else:
                error_type = None
            if metadata is None:
                call = _call_record(
                    "rewrite",
                    [source["id"]],
                    {
                        "endpoint": endpoint,
                        "model": model,
                        "latency_seconds": round(time.monotonic() - started, 6),
                    },
                    errors[0],
                )
                if error_type:
                    call["error_type"] = error_type
                calls.append(call)
        record = {
            "id": source["id"],
            "split": source["split"],
            "index": source["index"],
            "source_hash": source["source_hash"],
            "decision_hash": decision_hash,
            "candidate_hash": stable_hash(candidate) if candidate else None,
            "prompt_version": REWRITE_PROMPT_VERSION,
            "model": model,
            "endpoint": endpoint,
            "mode": decision["mode"],
            "attempt": attempt,
            "accepted": not errors,
            "errors": errors,
            "candidate": candidate,
            "completed_at": utc_now(),
        }
        if error_type:
            record["error_type"] = error_type
            record["status"] = "error"
        attempts.append(record)
        if not errors:
            return attempts, calls
        # Service failures are not failed rewrite candidates. Persist one
        # resumable error and stop trying this row; otherwise a network outage
        # can incorrectly consume all content attempts and route the row to
        # manual review.
        if error_type:
            return attempts, calls
        feedback = "; ".join(errors)
    attempts.append(
        {
            "id": source["id"],
            "split": source["split"],
            "index": source["index"],
            "source_hash": source["source_hash"],
            "decision_hash": decision_hash,
            "prompt_version": REWRITE_PROMPT_VERSION,
            "model": model,
            "endpoint": endpoint,
            "mode": decision["mode"],
            "accepted": False,
            "status": "manual",
            "terminal_reason": "validation_exhaustion",
            "errors": [f"retry exhaustion after {max_attempts} attempts"],
            "completed_at": utc_now(),
        }
    )
    return attempts, calls


def rewrite(
    paths: PipelinePaths,
    *,
    workers: int = 16,
    max_attempts: int = 3,
    max_items: int | None = None,
    client: OpenCodeClient | None = None,
) -> dict:
    if workers < 1 or max_attempts < 1 or (max_items is not None and max_items < 1):
        raise ValueError("workers, max attempts, and max items must be positive")
    judges = _current_judges(paths)
    _require_full_judge(paths, judges)
    decisions = _load_complete_decisions(paths, judges)
    sources = {
        row["id"]: row for split in SPLITS for row in read_jsonl(paths.source(split))
    }
    target_ids: set[str] | None = None

    def pending_queue() -> list[tuple[dict, dict]]:
        queue = []
        histories_by_split: dict[str, dict[str, list[dict]]] = {}
        latest_by_split: dict[str, dict[str, dict]] = {}
        for split in SPLITS:
            histories: dict[str, list[dict]] = {}
            for record in read_jsonl(paths.rewrites(split)):
                histories.setdefault(record["id"], []).append(record)
            histories_by_split[split] = histories
            latest_by_split[split] = {
                row_id: history[-1] for row_id, history in histories.items()
            }
        for row_id, decision in decisions.items():
            if decision["decision"] != "rewrite":
                continue
            if target_ids is not None and row_id not in target_ids:
                continue
            if decision.get("mode") not in {"surface", "date"}:
                raise RuntimeError(f"{row_id} has invalid rewrite mode {decision.get('mode')!r}")
            source = sources[row_id]
            decision_hash = stable_hash(
                {
                    "decision": decision.get("decision"),
                    "reason": decision.get("reason"),
                    "mode": decision.get("mode"),
                }
            )
            latest = latest_by_split[source["split"]].get(row_id)
            terminal_manual = False
            manual_accepted = bool(
                latest
                and latest.get("accepted") is True
                and latest.get("status") == "manual_accepted"
            )
            if latest and latest.get("status") == "manual":
                if latest.get("terminal_reason") == "validation_exhaustion":
                    terminal_manual = True
                elif "terminal_reason" not in latest:
                    # Compatibility for v1 records. A legacy manual marker is
                    # terminal only when the immediately preceding attempt was
                    # a model candidate failure, not an API/transport failure.
                    history = histories_by_split[source["split"]][row_id]
                    prior = history[-2] if len(history) > 1 else {}
                    terminal_manual = not bool(prior.get("error_type"))
            if (
                latest
                and latest.get("source_hash") == source["source_hash"]
                and latest.get("decision_hash") == decision_hash
                and latest.get("prompt_version") == REWRITE_PROMPT_VERSION
                and (
                    manual_accepted
                    or canonical_model_family(latest.get("model"))
                    == canonical_model_family(REWRITE_MODEL)
                )
                and (latest.get("accepted") is True or terminal_manual)
            ):
                continue
            queue.append((source, decision))
        queue.sort(key=lambda item: (SPLITS.index(item[0]["split"]), item[0]["index"]))
        return queue

    if max_items is not None:
        target_ids = {source["id"] for source, _ in pending_queue()[:max_items]}

    def run_route(model: str, endpoint: str) -> str | None:
        queue = pending_queue()
        if not queue:
            return None
        items = iter(queue)
        halt_reason = None
        consecutive_api_errors = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {}

            def submit_next() -> bool:
                try:
                    source, decision = next(items)
                except StopIteration:
                    return False
                future = pool.submit(
                    _rewrite_one,
                    source,
                    decision,
                    client,
                    max_attempts,
                    model,
                    endpoint,
                )
                futures[future] = source
                return True

            for _ in range(min(workers, len(queue))):
                submit_next()
            while futures:
                completed, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in completed:
                    source = futures.pop(future)
                    attempts, calls = future.result()
                    append_jsonl(paths.rewrites(source["split"]), attempts)
                    append_jsonl(paths.calls, calls)
                    stop_errors = {
                        row.get("error_type")
                        for row in attempts
                        if row.get("error_type") in {"free_usage_limit", "rate_limit", "region_opt_in"}
                    }
                    if stop_errors:
                        halt_reason = sorted(stop_errors)[0]
                    elif any(row.get("error_type") == "api" for row in attempts):
                        consecutive_api_errors += 1
                        if consecutive_api_errors >= 3:
                            halt_reason = "api"
                    else:
                        consecutive_api_errors = 0
                if halt_reason:
                    for future in list(futures):
                        if future.cancel():
                            futures.pop(future)
                else:
                    for _ in completed:
                        submit_next()
        return halt_reason

    client = client or OpenCodeClient()
    halt_reason = run_route(REWRITE_FREE_MODEL, REWRITE_FREE_ENDPOINT)
    if halt_reason == "free_usage_limit":
        halt_reason = run_route(REWRITE_PAID_MODEL, REWRITE_PAID_ENDPOINT)
    result = status(paths)
    if halt_reason:
        result["halted"] = halt_reason
    return result


def _require_full_judge(paths: PipelinePaths, judges: dict[str, dict] | None = None) -> None:
    judges = judges or _current_judges(paths)
    for split, expected in EXPECTED_COUNTS.items():
        sources = read_jsonl(paths.source(split))
        complete = sum(row["id"] in judges for row in sources)
        errors = sum(judges.get(row["id"], {}).get("action") == "error" for row in sources)
        if len(sources) != expected or complete != expected or errors:
            raise RuntimeError(
                f"Judge is not complete for {split}: {complete}/{expected}, unresolved errors={errors}"
            )


def _assemble_candidates(
    paths: PipelinePaths, judges: dict[str, dict], decisions: dict[str, dict]
) -> tuple[dict[str, list[dict]], set[str]]:
    output = {split: [] for split in SPLITS}
    requires_external: set[str] = set()
    rewrite_maps = {split: read_latest_by_id(paths.rewrites(split)) for split in SPLITS}
    for split in SPLITS:
        for source in read_jsonl(paths.source(split)):
            verdict = judges[source["id"]]
            decision = decisions.get(source["id"])
            candidate = {"question": source["question"], "answer": source["answer"]}
            calculations = [
                {"expression": item["expression"], "result": item["result"]}
                for item in source["calculations"]
            ]
            changed = False
            mode = "surface"
            if decision:
                mode = decision.get("mode", "surface")
                if decision["decision"] == "rewrite":
                    staged = rewrite_maps[split].get(source["id"])
                    decision_hash = stable_hash(
                        {
                            "decision": decision.get("decision"),
                            "reason": decision.get("reason"),
                            "mode": decision.get("mode"),
                        }
                    )
                    if (
                        not staged
                        or staged.get("accepted") is not True
                        or staged.get("decision_hash") != decision_hash
                    ):
                        raise RuntimeError(f"Approved rewrite has no accepted candidate: {source['id']}")
                    candidate = staged["candidate"]
                    calculations = candidate["calculations"]
                    changed = True
                elif decision["decision"] == "manual":
                    candidate = {"question": decision.get("question"), "answer": decision.get("answer")}
                    calculations = decision.get("calculations")
                    manual = {**candidate, "calculations": calculations}
                    errors = validate_candidate(source, manual, mode)
                    if errors:
                        raise RuntimeError(f"Invalid manual candidate {source['id']}: {'; '.join(errors)}")
                    changed = True
                requires_external.add(source["id"])
            assembled = {
                "id": source["id"],
                "split": split,
                "index": source["index"],
                "question": candidate["question"],
                "answer": candidate["answer"],
                "calculations": calculations,
                "source_hash": source["source_hash"],
                "changed": changed,
                "mode": mode,
            }
            assembled["candidate_hash"] = stable_hash(
                {"question": assembled["question"], "answer": assembled["answer"], "calculations": calculations}
            )
            output[split].append(assembled)
    return output, requires_external


def _verify_one(row: dict, source: dict, client: OpenCodeClient) -> tuple[dict, list[dict]]:
    errors = validate_candidate(source, row, row["mode"])
    calls: list[dict] = []
    solver_answer = None
    temporal_action = None
    temporal_reason = None
    if not errors:
        try:
            solver, metadata = client.responses_json(
                model=SOLVER_MODEL,
                system=SOLVER_SYSTEM_PROMPT,
                user=row["question"],
                max_output_tokens=4096,
            )
            calls.append(_call_record("verify-solver", [row["id"]], metadata))
            solver_answer = solver.get("answer") if isinstance(solver, dict) else None
            if not isinstance(solver_answer, str) or not answers_equal(
                solver_answer, extract_final_answer(row["answer"])
            ):
                errors.append(
                    f"independent solver answer {solver_answer!r} disagrees with {extract_final_answer(row['answer'])!r}"
                )
        except Exception as exc:
            errors.append(f"solver error: {type(exc).__name__}: {exc}")
            calls.append(
                _call_record(
                    "verify-solver", [row["id"]], {"endpoint": RESPONSES_ENDPOINT, "model": SOLVER_MODEL}, errors[-1]
                )
            )
    if not errors:
        temporal_metadata = None
        try:
            value, metadata = client.chat_json(
                model=JUDGE_MODEL,
                system=JUDGE_SYSTEM_PROMPT,
                user=judge_user_payload([row]),
                max_tokens=1024,
                endpoint=JUDGE_ENDPOINT,
            )
            temporal_metadata = metadata
            verdict = _validate_judge_response(value, [row["id"]])[0]
            calls.append(_call_record("verify-temporal", [row["id"]], metadata))
            temporal_action, temporal_reason = verdict["action"], verdict["reason"]
            if temporal_action != "keep":
                errors.append(f"final temporal judge returned {temporal_action}: {temporal_reason}")
        except Exception as exc:
            errors.append(f"temporal judge error: {type(exc).__name__}: {exc}")
            calls.append(
                _call_record(
                    "verify-temporal",
                    [row["id"]],
                    temporal_metadata or {"endpoint": JUDGE_ENDPOINT, "model": JUDGE_MODEL},
                    errors[-1],
                )
            )
    return (
        {
            "id": row["id"],
            "split": row["split"],
            "index": row["index"],
            "candidate_hash": row["candidate_hash"],
            "accepted": not errors,
            "errors": errors,
            "solver_answer": solver_answer,
            "temporal_action": temporal_action,
            "temporal_reason": temporal_reason,
            "solver_prompt_version": SOLVER_PROMPT_VERSION,
            "solver_model": SOLVER_MODEL,
            "judge_prompt_version": JUDGE_PROMPT_VERSION,
            "judge_model": JUDGE_MODEL,
            "completed_at": utc_now(),
        },
        calls,
    )


def verify(
    paths: PipelinePaths,
    *,
    workers: int = 8,
    max_items: int | None = None,
    client: OpenCodeClient | None = None,
) -> dict:
    judges = _current_judges(paths)
    _require_full_judge(paths, judges)
    decisions = _load_complete_decisions(paths, judges)
    candidates, requires_external = _assemble_candidates(paths, judges, decisions)
    sources = {
        row["id"]: row for split in SPLITS for row in read_jsonl(paths.source(split))
    }
    deterministic_errors = []
    for split in SPLITS:
        for row in candidates[split]:
            errors = validate_candidate(sources[row["id"]], row, row["mode"])
            if errors:
                deterministic_errors.append({"id": row["id"], "errors": errors})
    atomic_write_json(paths.audit_dir / "deterministic-verification.json", deterministic_errors)
    if deterministic_errors:
        raise RuntimeError(f"Deterministic verification failed for {len(deterministic_errors)} rows")

    duplicates = cross_split_duplicates(candidates["train"], candidates["test"])
    atomic_write_json(paths.audit_dir / "cross-split-duplicates.json", duplicates)
    if duplicates:
        raise RuntimeError(f"Found {len(duplicates)} exact/near cross-split duplicates")

    queue = []
    for split in SPLITS:
        latest = read_latest_by_id(paths.verify(split))
        for row in candidates[split]:
            if row["id"] not in requires_external:
                continue
            cached = latest.get(row["id"])
            if (
                cached
                and cached.get("accepted") is True
                and cached.get("candidate_hash") == row["candidate_hash"]
                and cached.get("solver_prompt_version") == SOLVER_PROMPT_VERSION
                and cached.get("solver_model") == SOLVER_MODEL
                and cached.get("judge_prompt_version") == JUDGE_PROMPT_VERSION
                and canonical_model_family(cached.get("judge_model"))
                == canonical_model_family(JUDGE_MODEL)
            ):
                continue
            queue.append(row)
    queue.sort(key=lambda row: (SPLITS.index(row["split"]), row["index"]))
    if max_items is not None:
        queue = queue[:max_items]
    if queue:
        client = client or OpenCodeClient()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_verify_one, row, sources[row["id"]], client): row for row in queue
            }
            for future in as_completed(futures):
                result, calls = future.result()
                append_jsonl(paths.verify(result["split"]), [result])
                append_jsonl(paths.calls, calls)
    return status(paths)


def package(paths: PipelinePaths) -> dict:
    judges = _current_judges(paths)
    _require_full_judge(paths, judges)
    decisions = _load_complete_decisions(paths, judges)
    candidates, requires_external = _assemble_candidates(paths, judges, decisions)
    verification = {
        row_id: row for split in SPLITS for row_id, row in read_latest_by_id(paths.verify(split)).items()
    }
    candidate_hashes = {
        row["id"]: row["candidate_hash"] for split in SPLITS for row in candidates[split]
    }
    failures = [
        row_id
        for row_id in requires_external
        if not (
            (record := verification.get(row_id))
            and record.get("accepted") is True
            and record.get("candidate_hash") == candidate_hashes[row_id]
            and record.get("solver_prompt_version") == SOLVER_PROMPT_VERSION
            and record.get("solver_model") == SOLVER_MODEL
            and record.get("judge_prompt_version") == JUDGE_PROMPT_VERSION
            and canonical_model_family(record.get("judge_model"))
            == canonical_model_family(JUDGE_MODEL)
        )
    ]
    if failures:
        raise RuntimeError(f"Verification gate is incomplete or failed for {len(failures)} rows")

    duplicates = cross_split_duplicates(candidates["train"], candidates["test"])
    if duplicates:
        raise RuntimeError(f"Found {len(duplicates)} exact/near cross-split duplicates")
    for split, expected in EXPECTED_COUNTS.items():
        rows = candidates[split]
        if len(rows) != expected:
            raise RuntimeError(f"Final {split} count is {len(rows)}, expected {expected}")
        expected_ids = [f"gsm8k-{DATASET_SUBSET}-{split}-{index:06d}" for index in range(expected)]
        if [row["id"] for row in rows] != expected_ids:
            raise RuntimeError(f"Final {split} IDs/order do not match the official split")
        final_rows = [{key: row[key] for key in ("id", "question", "answer")} for row in rows]
        atomic_write_jsonl(paths.packaged(split), final_rows)
    raw_test = [
        {"id": row["id"], "question": row["question"], "answer": row["raw_answer"]}
        for row in read_jsonl(paths.source("test"))
    ]
    atomic_write_jsonl(paths.data_dir / "test.raw.jsonl", raw_test)
    package_manifest = {
        "packaged_at": utc_now(),
        "source_manifest": json.loads(paths.manifest.read_text(encoding="utf-8")),
        "counts": EXPECTED_COUNTS,
        "changed_rows": sum(row["changed"] for split in SPLITS for row in candidates[split]),
        "files": {
            split: {"path": str(paths.packaged(split)), "sha256": stable_hash(read_jsonl(paths.packaged(split)))}
            for split in SPLITS
        },
        "raw_test": str(paths.data_dir / "test.raw.jsonl"),
    }
    atomic_write_json(paths.data_dir / "manifest.json", package_manifest)
    return package_manifest


def status(paths: PipelinePaths) -> dict:
    result: dict = {"artifact_root": str(paths.root), "prepared": paths.manifest.exists(), "splits": {}}
    if paths.regex_manifest.exists():
        result["regex"] = json.loads(paths.regex_manifest.read_text(encoding="utf-8")).get("splits", {})
    else:
        result["regex"] = {"status": "not run"}
    judges = _current_judges(paths) if paths.manifest.exists() else {}
    for split, expected in EXPECTED_COUNTS.items():
        sources = read_jsonl(paths.source(split))
        actions = Counter(judges.get(row["id"], {}).get("action", "pending") for row in sources)
        rewrites = read_latest_by_id(paths.rewrites(split))
        result["splits"][split] = {
            "source": len(sources),
            "expected": expected,
            "judged": sum(actions[action] for action in VALID_JUDGE_ACTIONS),
            "errors": actions["error"],
            "pending": actions["pending"],
            "actions": dict(sorted(actions.items())),
            "rewrites_accepted": sum(row.get("accepted") is True for row in rewrites.values()),
            "rewrites_manual": sum(row.get("status") == "manual" for row in rewrites.values()),
            "rewrite_errors": sum(row.get("status") == "error" for row in rewrites.values()),
            "verified": sum(
                row.get("accepted") is True for row in read_latest_by_id(paths.verify(split)).values()
            ),
        }
    decisions = read_latest_by_id(paths.decisions)
    result["review"] = {
        "flagged": len(decisions),
        "decided": sum(
            row.get("decision") in VALID_REVIEW_DECISIONS
            and isinstance(row.get("reason"), str)
            and bool(row.get("reason", "").strip())
            for row in decisions.values()
        ),
    }
    result["packaged"] = all(paths.packaged(split).exists() for split in SPLITS)
    return result
