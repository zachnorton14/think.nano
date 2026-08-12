import json

import pytest

from dev.history_event.client import TransportError
from dev.history_event.config import (
    GOLD_ANSWER_PROMPT_VERSION,
    PipelinePaths,
)
from dev.history_event.gold import (
    MalformedBatch,
    _error_kind,
    _call_with_recovery,
    _latest_matching,
    gold_status,
    run_gold,
    validate_answer_year,
    validate_batch,
)
from dev.history_event.io import append_jsonl, write_jsonl


def event(index: int, year: int = 1901) -> dict:
    return {
        "id": f"history-event-{index:06d}",
        "event_year": year,
        "event_description": f"Specific event {index}",
        "recall_question": f"What happened in event {index}?",
        "source_hash": f"hash-{index}",
    }


class FakeClient:
    def __init__(self, *, accepted=True, fail=False):
        self.accepted = accepted
        self.fail = fail
        self.calls = 0

    def chat_json(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise TransportError("offline")
        items = json.loads(kwargs["user"])
        if "question" in items[0]:
            payload = [
                {"id": item["id"], "answer": "It occurred in 1901 and involved a specific treaty."}
                for item in items
            ]
        else:
            payload = [
                {"id": item["id"], "accepted": self.accepted, "reason": "specific and correct"}
                for item in items
            ]
        return payload, {
            "timestamp": "2026-05-29T00:00:00Z",
            "endpoint": kwargs["endpoint"],
            "model": kwargs["model"],
            "latency_seconds": 0.01,
            "prompt_tokens": 10,
            "completion_tokens": 10,
            "cached_tokens": 0,
            "reported_cost": 0.001,
            "usage": {},
        }


def test_batch_schema_rejects_missing_duplicate_and_malformed_output():
    expected = ["a", "b"]
    with pytest.raises(MalformedBatch, match="id mismatch"):
        validate_batch([{"id": "a", "answer": "x"}], expected, stage="answer")
    with pytest.raises(MalformedBatch, match="duplicate"):
        validate_batch(
            [{"id": "a", "answer": "x"}, {"id": "a", "answer": "y"}],
            expected,
            stage="answer",
        )
    with pytest.raises(MalformedBatch, match="JSON array"):
        validate_batch("not-json-shape", expected, stage="answer")
    assert _error_kind(ValueError("invalid JSON")) == "malformed"


def test_year_validation_is_deterministic_and_rejects_conflicts():
    assert validate_answer_year("The event happened in 1901.", 1901)[0] is True
    assert validate_answer_year("The event happened around the turn of the century.", 1901)[0] is False
    accepted, reason, years = validate_answer_year("It began in 1901, not 1902.", 1901)
    assert accepted is False
    assert years == [1901, 1902]
    assert "conflicting" in reason


def test_canonical_alias_cache_reuse_prompt_invalidation_and_error_retry(tmp_path):
    path = tmp_path / "answers.jsonl"
    base = {
        "id": "history-event-000000",
        "source_hash": "hash-0",
        "stage": "answer",
        "status": "ok",
        "prompt_version": GOLD_ANSWER_PROMPT_VERSION,
        "model": "deepseek-v4-flash-free",
        "canonical_model_family": "deepseek-v4-flash",
    }
    append_jsonl(path, base)
    assert "history-event-000000" in _latest_matching(
        path, stage="answer", prompt_version=GOLD_ANSWER_PROMPT_VERSION,
        model="deepseek-v4-flash",
    )
    assert not _latest_matching(
        path, stage="answer", prompt_version="new-prompt", model="deepseek-v4-flash"
    )
    assert not _latest_matching(
        path, stage="answer", prompt_version=GOLD_ANSWER_PROMPT_VERSION, model="unrelated-model"
    )
    append_jsonl(path, {**base, "status": "error", "model": "deepseek-v4-flash"})
    latest = _latest_matching(
        path, stage="answer", prompt_version=GOLD_ANSWER_PROMPT_VERSION,
        model="deepseek-v4-flash",
    )
    assert latest[base["id"]]["status"] == "error"


def test_probe_is_resumable_and_factual_rejection_is_fail_closed(tmp_path):
    paths = PipelinePaths(tmp_path)
    write_jsonl(paths.recall_candidates, [event(0), event(1)])
    client = FakeClient(accepted=False)
    result = run_gold(paths, probe_only=True, client=client)
    assert result["probe"]["successful"] is True
    assert result["retained"] == 0
    calls_after_first = client.calls
    rerun = run_gold(paths, probe_only=True, client=client)
    assert rerun["answer_run"]["written"] == 0
    assert rerun["judge_run"]["written"] == 0
    assert client.calls == calls_after_first


def test_transport_failures_remain_resumable_errors(tmp_path):
    paths = PipelinePaths(tmp_path)
    write_jsonl(paths.recall_candidates, [event(0), event(1)])
    result = run_gold(paths, probe_only=True, client=FakeClient(fail=True))
    assert result["probe"]["successful"] is False
    assert not paths.probe.exists()
    status = gold_status(paths)
    assert status["unresolved_errors"] == 2
    assert status["complete"] is False


def test_transport_outage_does_not_bisect_batches():
    rows = [event(index) for index in range(8)]
    calls = 0

    def fail(_batch):
        nonlocal calls
        calls += 1
        raise TransportError("offline")

    records, audit = _call_with_recovery(
        rows,
        stage="answer",
        call=fail,
        prompt_version=GOLD_ANSWER_PROMPT_VERSION,
        model="deepseek-v4-flash",
        endpoint="https://example.invalid",
    )
    assert calls == 2
    assert len(audit) == 2
    assert len(records) == 8
    assert all(record["error_kind"] == "transport" for record in records)
