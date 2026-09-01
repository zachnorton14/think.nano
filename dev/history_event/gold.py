"""Resumable two-stage DeepSeek reference-answer construction."""

from __future__ import annotations

import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .client import APIError, OpenCodeClient
from .config import (
    GOLD_ANSWER_PROMPT_VERSION,
    GOLD_JUDGE_PROMPT_VERSION,
    OPENCODE_ENDPOINT,
    OPENCODE_MODEL,
    PAPER_GOLD_COUNT,
    PipelinePaths,
    canonical_model_family,
)
from .io import append_jsonl, iter_jsonl, write_json, write_jsonl
from .prompts import ANSWER_SYSTEM, JUDGE_SYSTEM


YEAR_RE = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)")
TRANSIENT_ERROR_KINDS = {"rate_limit", "region", "transport", "malformed"}


class MalformedBatch(ValueError):
    pass


def validate_batch(payload: object, expected_ids: list[str], *, stage: str) -> list[dict]:
    if isinstance(payload, dict):
        payload = payload.get("items")
    if not isinstance(payload, list):
        raise MalformedBatch("response must be a JSON array (or an object with an items array)")
    if not all(isinstance(item, dict) for item in payload):
        raise MalformedBatch("every response item must be an object")
    ids = [item.get("id") for item in payload]
    if len(ids) != len(set(ids)):
        raise MalformedBatch("response contains duplicate ids")
    missing = sorted(set(expected_ids) - set(ids))
    extra = sorted(set(ids) - set(expected_ids))
    if missing or extra:
        raise MalformedBatch(f"id mismatch: missing={missing}, extra={extra}")
    required = ("answer",) if stage == "answer" else ("accepted", "reason")
    by_id = {item["id"]: item for item in payload}
    for item in payload:
        for field in required:
            if field not in item:
                raise MalformedBatch(f"{item.get('id')} is missing {field}")
        if stage == "answer" and not isinstance(item["answer"], str):
            raise MalformedBatch(f"{item['id']} answer must be a string")
        if stage == "judge" and not isinstance(item["accepted"], bool):
            raise MalformedBatch(f"{item['id']} accepted must be boolean")
    return [by_id[item_id] for item_id in expected_ids]


def validate_answer_year(answer: str, event_year: int) -> tuple[bool, str, list[int]]:
    years = [int(value) for value in YEAR_RE.findall(answer)]
    unique = sorted(set(years))
    if event_year not in unique:
        return False, f"answer does not explicitly state {event_year}", unique
    conflicts = [year for year in unique if year != event_year]
    if conflicts:
        return False, f"answer contains conflicting year(s): {conflicts}", unique
    return True, "correct year stated without a conflicting year", unique


def _latest_matching(
    path: Path,
    *,
    stage: str,
    prompt_version: str,
    model: str,
) -> dict[str, dict]:
    family = canonical_model_family(model)
    latest: dict[str, dict] = {}
    for record in iter_jsonl(path):
        if (
            record.get("stage") == stage
            and record.get("prompt_version") == prompt_version
            and record.get("canonical_model_family") == family
        ):
            latest[record["id"]] = record
    return latest


def reusable(record: dict | None, row: dict) -> bool:
    return bool(record and record.get("status") != "error" and record.get("source_hash") == row["source_hash"])


def _error_kind(exc: Exception) -> str:
    if isinstance(exc, (MalformedBatch, ValueError)):
        return "malformed"
    if isinstance(exc, APIError):
        return exc.error_kind
    return "unexpected"


def _call_with_recovery(
    batch: list[dict],
    *,
    stage: str,
    call: Callable[[list[dict]], tuple[object, dict]],
    prompt_version: str,
    model: str,
    endpoint: str,
) -> tuple[list[dict], list[dict]]:
    """Retry once, bisect, then leave singleton failures as resumable errors."""
    calls: list[dict] = []
    expected = [row["id"] for row in batch]
    last_exc: Exception | None = None
    for attempt in (1, 2):
        call_id = str(uuid.uuid4())
        try:
            payload, metadata = call(batch)
            output = validate_batch(payload, expected, stage=stage)
            calls.append({
                "call_id": call_id,
                "stage": stage,
                "attempt": attempt,
                "ids": expected,
                "status": "ok",
                **metadata,
            })
            records = []
            for row, item in zip(batch, output):
                base = {
                    "id": row["id"],
                    "source_hash": row["source_hash"],
                    "stage": stage,
                    "status": "ok",
                    "prompt_version": prompt_version,
                    "model": model,
                    "canonical_model_family": canonical_model_family(model),
                    "endpoint": endpoint,
                    "call_id": call_id,
                    "timestamp": metadata.get("timestamp"),
                }
                if stage == "answer":
                    accepted, reason, years = validate_answer_year(item["answer"], row["event_year"])
                    base.update({
                        "answer": item["answer"].strip(),
                        "year_accepted": accepted,
                        "year_reason": reason,
                        "years_found": years,
                    })
                else:
                    base.update({"accepted": item["accepted"], "reason": str(item["reason"])[:1000]})
                records.append(base)
            return records, calls
        except Exception as exc:  # every failed call is audited and fail-closed
            last_exc = exc
            failure_metadata = getattr(exc, "call_metadata", {})
            calls.append({
                "call_id": call_id,
                "stage": stage,
                "attempt": attempt,
                "ids": expected,
                "status": "error",
                "error_kind": _error_kind(exc),
                "error": str(exc)[:2000],
                "timestamp": failure_metadata.get("timestamp", datetime.now(timezone.utc).isoformat()),
                "model": model,
                "endpoint": endpoint,
                **{
                    key: failure_metadata.get(key)
                    for key in (
                        "latency_seconds", "prompt_tokens", "completion_tokens",
                        "cached_tokens", "reported_cost", "usage",
                    )
                    if key in failure_metadata
                },
            })
    # Bisection repairs content/schema problems by reducing prompt complexity.
    # It cannot repair provider, region, rate-limit, or network failures and would
    # only multiply calls during an outage.
    if len(batch) > 1 and _error_kind(last_exc or RuntimeError("unknown error")) == "malformed":
        midpoint = len(batch) // 2
        left_records, left_calls = _call_with_recovery(
            batch[:midpoint], stage=stage, call=call, prompt_version=prompt_version,
            model=model, endpoint=endpoint,
        )
        right_records, right_calls = _call_with_recovery(
            batch[midpoint:], stage=stage, call=call, prompt_version=prompt_version,
            model=model, endpoint=endpoint,
        )
        return left_records + right_records, calls + left_calls + right_calls
    return [{
        "id": row["id"],
        "source_hash": row["source_hash"],
        "stage": stage,
        "status": "error",
        "prompt_version": prompt_version,
        "model": model,
        "canonical_model_family": canonical_model_family(model),
        "endpoint": endpoint,
        "error_kind": _error_kind(last_exc or RuntimeError("unknown error")),
        "error": str(last_exc)[:2000],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    } for row in batch], calls


def _batches(rows: list[dict], size: int) -> list[list[dict]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def _run_stage(
    rows: list[dict],
    *,
    stage: str,
    batch_size: int,
    workers: int,
    output: Path,
    calls_path: Path,
    call: Callable[[list[dict]], tuple[object, dict]],
    prompt_version: str,
    model: str,
    endpoint: str,
) -> dict:
    pending_batches = _batches(rows, batch_size)
    written = errors = 0
    active_workers = workers
    # Bounded waves let repeated provider failures lower concurrency before all work is submitted.
    while pending_batches:
        wave_size = max(active_workers, 1) * 2
        wave, pending_batches = pending_batches[:wave_size], pending_batches[wave_size:]
        transient = 0

        def execute(batch: list[dict]):
            return _call_with_recovery(
                batch, stage=stage, call=call, prompt_version=prompt_version,
                model=model, endpoint=endpoint,
            )

        with ThreadPoolExecutor(max_workers=active_workers) as executor:
            futures = [executor.submit(execute, batch) for batch in wave]
            for future in as_completed(futures):
                records, calls = future.result()
                for call_record in calls:
                    append_jsonl(calls_path, call_record)
                for record in records:
                    append_jsonl(output, record)
                    written += 1
                    if record["status"] == "error":
                        errors += 1
                        transient += record.get("error_kind") in TRANSIENT_ERROR_KINDS
        if active_workers > 32 and transient >= 3:
            active_workers = 32
    return {"written": written, "errors": errors, "workers_final": active_workers}


def _answer_call(client: OpenCodeClient, model: str, endpoint: str, batch: list[dict]):
    user = json.dumps(
        [{"id": row["id"], "question": row["recall_question"]} for row in batch],
        ensure_ascii=False,
    )
    return client.chat_json(
        model=model, endpoint=endpoint, system=ANSWER_SYSTEM, user=user,
        # DeepSeek can spend about 2K hidden reasoning tokens on ambiguous recent
        # events before emitting JSON, so preserve 4K headroom even for singletons.
        max_tokens=max(4096, len(batch) * 700),
    )


def _judge_call(client: OpenCodeClient, model: str, endpoint: str, batch: list[dict]):
    user = json.dumps(
        [{
            "id": row["id"],
            "event_description": row["event_description"],
            "event_year": row["event_year"],
            "answer": row["gold_answer"],
        } for row in batch],
        ensure_ascii=False,
    )
    return client.chat_json(
        model=model, endpoint=endpoint, system=JUDGE_SYSTEM, user=user,
        max_tokens=max(1024, len(batch) * 250),
    )


def run_gold(
    paths: PipelinePaths,
    *,
    batch_size: int = 8,
    workers: int = 64,
    probe_only: bool = False,
    model: str = OPENCODE_MODEL,
    endpoint: str = OPENCODE_ENDPOINT,
    client: OpenCodeClient | None = None,
) -> dict:
    if not paths.recall_candidates.exists():
        raise RuntimeError("source data is missing; run `prepare` first")
    if not probe_only and not paths.probe.exists():
        raise RuntimeError("paid route has not been probed; run `gold --probe` first")
    candidates = list(iter_jsonl(paths.recall_candidates))
    answer_latest = _latest_matching(
        paths.answer_audit, stage="answer", prompt_version=GOLD_ANSWER_PROMPT_VERSION, model=model
    )
    judge_latest = _latest_matching(
        paths.judge_audit, stage="judge", prompt_version=GOLD_JUDGE_PROMPT_VERSION, model=model
    )
    if probe_only:
        unresolved = [
            row for row in candidates
            if not reusable(answer_latest.get(row["id"]), row)
            or (
                answer_latest[row["id"]].get("year_accepted")
                and not reusable(judge_latest.get(row["id"]), row)
            )
        ]
        scope = unresolved[:2]
    else:
        scope = candidates
    pending_answers = [row for row in scope if not reusable(answer_latest.get(row["id"]), row)]
    active_client = client or OpenCodeClient()
    answer_summary = _run_stage(
        pending_answers,
        stage="answer", batch_size=min(batch_size, 2) if probe_only else batch_size,
        workers=min(workers, 2) if probe_only else workers,
        output=paths.answer_audit, calls_path=paths.call_log,
        call=lambda batch: _answer_call(active_client, model, endpoint, batch),
        prompt_version=GOLD_ANSWER_PROMPT_VERSION, model=model, endpoint=endpoint,
    ) if pending_answers else {"written": 0, "errors": 0, "workers_final": workers}

    answer_latest = _latest_matching(
        paths.answer_audit, stage="answer", prompt_version=GOLD_ANSWER_PROMPT_VERSION, model=model
    )
    answer_ready = []
    scope_ids = {row["id"] for row in scope}
    for row in candidates:
        record = answer_latest.get(row["id"])
        if row["id"] in scope_ids and reusable(record, row) and record.get("year_accepted"):
            answer_ready.append({**row, "gold_answer": record["answer"]})
    judge_latest = _latest_matching(
        paths.judge_audit, stage="judge", prompt_version=GOLD_JUDGE_PROMPT_VERSION, model=model
    )
    pending_judges = [row for row in answer_ready if not reusable(judge_latest.get(row["id"]), row)]
    judge_summary = _run_stage(
        pending_judges,
        stage="judge", batch_size=min(batch_size, 2) if probe_only else batch_size,
        workers=min(workers, 2) if probe_only else workers,
        output=paths.judge_audit, calls_path=paths.call_log,
        call=lambda batch: _judge_call(active_client, model, endpoint, batch),
        prompt_version=GOLD_JUDGE_PROMPT_VERSION, model=model, endpoint=endpoint,
    ) if pending_judges else {"written": 0, "errors": 0, "workers_final": workers}

    result = gold_status(paths, model=model)
    if probe_only:
        probe_errors = answer_summary["errors"] + judge_summary["errors"]
        probe = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "endpoint": endpoint,
            "ids": [row["id"] for row in scope],
            "successful": probe_errors == 0,
            "errors": probe_errors,
        }
        if probe["successful"]:
            write_json(paths.probe, probe)
        result["probe"] = probe
    return {**result, "answer_run": answer_summary, "judge_run": judge_summary}


def gold_status(paths: PipelinePaths, *, model: str = OPENCODE_MODEL) -> dict:
    candidates = list(iter_jsonl(paths.recall_candidates))
    answers = _latest_matching(
        paths.answer_audit, stage="answer", prompt_version=GOLD_ANSWER_PROMPT_VERSION, model=model
    )
    judges = _latest_matching(
        paths.judge_audit, stage="judge", prompt_version=GOLD_JUDGE_PROMPT_VERSION, model=model
    )
    answer_ok = [row for row in candidates if reusable(answers.get(row["id"]), row)]
    year_ok = [row for row in answer_ok if answers[row["id"]].get("year_accepted")]
    judged = [row for row in year_ok if reusable(judges.get(row["id"]), row)]
    retained = [row for row in judged if judges[row["id"]].get("accepted")]
    errors = sum(
        record.get("status") == "error"
        for record in list(answers.values()) + list(judges.values())
    )
    return {
        "candidates": len(candidates),
        "answers_complete": len(answer_ok),
        "answers_year_accepted": len(year_ok),
        "judgments_complete": len(judged),
        "retained": len(retained),
        "paper_retained": PAPER_GOLD_COUNT,
        "difference_from_paper": len(retained) - PAPER_GOLD_COUNT,
        "unresolved_errors": errors,
        "complete": len(answer_ok) == len(candidates) and len(judged) == len(year_ok) and errors == 0,
    }


def generate_gold_report(paths: PipelinePaths, *, model: str = OPENCODE_MODEL) -> dict:
    status = gold_status(paths, model=model)
    candidates = list(iter_jsonl(paths.recall_candidates))
    answers = _latest_matching(
        paths.answer_audit, stage="answer", prompt_version=GOLD_ANSWER_PROMPT_VERSION, model=model
    )
    judges = _latest_matching(
        paths.judge_audit, stage="judge", prompt_version=GOLD_JUDGE_PROMPT_VERSION, model=model
    )
    gold_rows = []
    for row in candidates:
        answer = answers.get(row["id"])
        judgment = judges.get(row["id"])
        if reusable(answer, row) and answer.get("year_accepted") and reusable(judgment, row) and judgment.get("accepted"):
            gold_rows.append({
                **row,
                "gold_answer": answer["answer"],
                "validation": {
                    "year_prompt_version": GOLD_ANSWER_PROMPT_VERSION,
                    "judge_prompt_version": GOLD_JUDGE_PROMPT_VERSION,
                    "model": judgment["model"],
                    "canonical_model_family": judgment["canonical_model_family"],
                    "judge_reason": judgment["reason"],
                },
            })
    write_jsonl(paths.gold_rows, gold_rows)
    write_json(paths.gold_report_json, status)
    markdown = f"""# DeepSeek gold-generation report

This is an independent DeepSeek-screened derivative, not the paper authors' Gemini subset.

- Recall candidates: {status['candidates']}
- Answers complete: {status['answers_complete']}
- Correct, non-conflicting year: {status['answers_year_accepted']}
- Factual judgments complete: {status['judgments_complete']}
- Retained gold answers: {status['retained']}
- Difference from the paper's 1,726 Gemini-retained rows: {status['difference_from_paper']:+d}
- Unresolved errors: {status['unresolved_errors']}
"""
    paths.gold_report_markdown.parent.mkdir(parents=True, exist_ok=True)
    paths.gold_report_markdown.write_text(markdown, encoding="utf-8")
    return status
