import json
from pathlib import Path

import pytest

from dev.vintage_core import backfill, prompts, regenerate


def _item(text="Question: What is two plus two?", revision=1):
    return {
        "query": text,
        "choices": ["3", "4", "5", "6"],
        "gold": 1,
        "backfilled": True,
        "source_idx": 0,
        "source_reason": "modern source",
        "source_src": "llm",
        "generation_revision": revision,
    }


def _entry(mode="revise"):
    return {
        "label": "demo",
        "source_idx": 0,
        "status": "reject",
        "reason": "answer is ambiguous",
        "mode": mode,
    }


def _context():
    task = {
        "label": "demo",
        "n": 1,
        "task_type": "multiple_choice",
        "num_fewshot": 0,
        "data": [{"query": "Question: Modern?", "choices": ["3", "4", "5", "6"], "gold": 1}],
    }
    pool = [{"idx": 0, "reason": "modern source", "src": "llm"}]
    return {
        "task": task,
        "pool": pool,
        "need": 1,
        "kept_n": 0,
        "benchmark": {"label": "demo", "description": "demo benchmark"},
        "source_by_idx": {0: pool[0]},
    }


def _wrapper(entry, previous, candidate):
    return {
        **entry,
        "manifest_fingerprint": regenerate._fingerprint(entry),
        "previous_generation_revision": previous["generation_revision"],
        "candidate": candidate,
    }


def _configure_tmp(tmp_path, monkeypatch, entry=None):
    entry = entry or _entry()
    ctx = _context()
    preview = _item()
    monkeypatch.setattr(backfill, "BACKFILL_DIR", str(tmp_path / "backfill"))
    monkeypatch.setattr(regenerate, "REGEN_DIR", str(tmp_path / "backfill" / "regeneration"))
    monkeypatch.setattr(regenerate.config, "REVIEW_DIR", str(tmp_path / "review"))
    monkeypatch.setattr(regenerate, "APPLIED_REPORT", str(tmp_path / "review" / "applied.md"))
    monkeypatch.setattr(regenerate, "_load_manifest", lambda enforce_inventory=True: [entry])
    monkeypatch.setattr(regenerate, "_task_contexts", lambda: {"demo": ctx})
    backfill._atomic_jsonl(backfill._preview_path("demo"), [preview])
    return entry, ctx, preview


def test_canonical_manifest_has_expected_inventory():
    entries = regenerate._load_manifest()
    assert len(entries) == 72
    assert sum(entry["status"] == "reject" for entry in entries) == 34
    assert sum(entry["status"] == "review" for entry in entries) == 38
    assert sum(entry["mode"] == "fresh" for entry in entries) == 23
    assert sum(entry["mode"] == "revise" for entry in entries) == 49
    arc = [entry for entry in entries if entry["label"] == "arc_challenge"]
    assert len(arc) == 19
    assert all(entry["mode"] == "fresh" for entry in arc)
    openbook_fresh = {
        entry["source_idx"]
        for entry in entries
        if entry["label"] == "openbook_qa" and entry["mode"] == "fresh"
    }
    assert openbook_fresh == {16, 71, 366, 431}


def test_regeneration_prompt_payloads_do_not_include_removed_original():
    schema = {"required_keys": ["choices", "gold", "query"], "choice_count": 4}
    fresh = prompts.regeneration_messages(
        "fresh", "multiple_choice", {"label": "arc"}, schema, "modern topic",
        approved_examples=[{"query": "old", "choices": ["a", "b"], "gold": 0}],
    )
    fresh_payload = json.loads(fresh[1]["content"])
    assert "item" not in fresh_payload
    assert "draft" not in fresh_payload
    assert fresh_payload["approved_examples"]

    revision = prompts.regeneration_messages(
        "revise", "multiple_choice", {"label": "demo"}, schema, "ambiguous",
        previous_item={"query": "draft", "choices": ["a", "b"], "gold": 0},
    )
    revision_payload = json.loads(revision[1]["content"])
    assert "item" not in revision_payload
    assert "approved_examples" not in revision_payload
    assert revision_payload["draft"]["query"] == "draft"


def test_stage_writes_isolated_candidate_and_preserves_preview(tmp_path, monkeypatch):
    entry, _, preview = _configure_tmp(tmp_path, monkeypatch)

    def fake_generate(entry, ctx, current, draft, max_tokens, retries, **options):
        candidate = _item("Question: What is three plus one?", revision=2)
        return _wrapper(entry, current, candidate)

    monkeypatch.setattr(regenerate, "_generate_candidate", fake_generate)
    preview_path = Path(backfill._preview_path("demo"))
    before = preview_path.read_text(encoding="utf-8")
    regenerate.stage(workers=1)
    after = preview_path.read_text(encoding="utf-8")
    assert after == before
    candidates = regenerate._load_candidates("demo")
    assert candidates[0]["candidate"]["query"].endswith("three plus one?")
    assert candidates[0]["candidate"]["generation_revision"] == 2
    assert json.loads(before)["query"] == preview["query"]


def test_rejected_candidate_retries_with_feedback_and_higher_temperature(tmp_path, monkeypatch):
    entry, _, preview = _configure_tmp(tmp_path, monkeypatch)
    first = _item("Question: First candidate?", revision=2)
    regenerate._write_candidates("demo", {0: _wrapper(entry, preview, first)})
    regenerate.reject_candidate("demo", 0, "still ambiguous")
    captured = {}

    def fake_generate(entry, ctx, current, draft, max_tokens, retries, **options):
        captured.update(options)
        captured["draft"] = draft
        second = _item("Question: Second candidate?", revision=3)
        return _wrapper(entry, current, second)

    monkeypatch.setattr(regenerate, "_generate_candidate", fake_generate)
    regenerate.stage(workers=1)
    assert captured["start_temperature_index"] == 1
    assert captured["rejection_feedback"] == "still ambiguous"
    assert captured["revision"] == 3
    assert captured["draft"]["query"].endswith("First candidate?")
    assert regenerate._load_candidate_rejections("demo") == {}


def test_candidate_validation_rejects_stale_baseline():
    entry = _entry()
    ctx = _context()
    previous = _item(revision=2)
    wrapper = _wrapper(entry, _item(revision=1), _item("Question: Candidate?", revision=2))
    with pytest.raises(backfill.ValidationError, match="baseline is stale"):
        regenerate._validate_candidate(entry, wrapper, ctx, previous)


def test_apply_is_offline_and_preserves_count(tmp_path, monkeypatch):
    entry, _, previous = _configure_tmp(tmp_path, monkeypatch)
    candidate = _item("Question: Applied candidate?", revision=2)
    regenerate._write_candidates("demo", {0: _wrapper(entry, previous, candidate)})
    monkeypatch.setattr(regenerate, "EXPECTED_TOTAL", 1)
    monkeypatch.setattr(
        regenerate,
        "chat_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("apply called API")),
    )
    regenerate.apply_candidates()
    merged = backfill._load_preview("demo")
    assert len(merged) == 1
    assert merged[0]["query"].endswith("Applied candidate?")
    assert (tmp_path / "review" / "applied.md").exists()


def test_apply_refuses_pending_candidate_rejection(tmp_path, monkeypatch):
    entry, _, previous = _configure_tmp(tmp_path, monkeypatch)
    candidate = _item("Question: Candidate?", revision=2)
    regenerate._write_candidates("demo", {0: _wrapper(entry, previous, candidate)})
    regenerate._write_candidate_rejections("demo", {0: "still wrong"})
    monkeypatch.setattr(regenerate, "EXPECTED_TOTAL", 1)
    with pytest.raises(SystemExit, match="pending candidate rejections"):
        regenerate.apply_candidates()
