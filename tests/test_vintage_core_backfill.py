import json

import pytest

from dev.vintage_core import backfill, client, log, prompts
from dev.vintage_core.temporal import science_anachronisms


def _mc_item(text="Question: What is two plus two?"):
    return {"query": text, "choices": ["3", "4", "5", "6"], "gold": 1}


def _task(label="demo"):
    return {
        "label": label,
        "n": 1,
        "task_type": "multiple_choice",
        "num_fewshot": 0,
        "data": [_mc_item("Question: Which modern device is shown?")],
    }


def _generated(source_idx=0):
    return {
        **_mc_item(),
        "backfilled": True,
        "source_idx": source_idx,
        "source_reason": "modern",
        "source_src": "llm",
        "generation_revision": 1,
    }


def test_target_count_only_restores_original_below_cutoff():
    assert backfill._target_count(100, 96) == 4
    assert backfill._target_count(1267, 1155) == 112
    assert backfill._target_count(1300, 1000) == 0
    assert backfill._target_count(3270, 1022) == 0
    assert log._target_backfill(3270, 1022) == 0


@pytest.mark.parametrize(
    "term",
    ["mitochondria", "continental drift", "quantum mechanics", "penicillin", "polymer"],
)
def test_science_blocklist_allows_pre1930_terms(term):
    assert science_anachronisms({"query": term, "choices": ["a", "b"]}) == []


@pytest.mark.parametrize(
    "term",
    ["neutron", "plate tectonics", "cell cycle", "photocopy", "ecosystem"],
)
def test_science_blocklist_rejects_post1930_terms(term):
    assert science_anachronisms({"query": term, "choices": ["a", "b"]})


def test_client_reports_length_truncation(monkeypatch):
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "choices": [{
                    "finish_reason": "length",
                    "message": {"content": '{"query":"partial'},
                }],
                "usage": {"completion_tokens": 640},
            }

    monkeypatch.setenv("OPENCODE_API_KEY", "test")
    monkeypatch.setattr(client.requests, "post", lambda *args, **kwargs: Response())
    client._COOLDOWN.clear()
    with pytest.raises(client.Truncated) as exc:
        client.chat([], "model", "https://example.test/v1", max_tokens=640, retries=1)
    assert exc.value.max_tokens == 640
    assert exc.value.partial_content.startswith("{")


def test_truncation_doubles_tokens_without_changing_temperature(monkeypatch):
    calls = []

    def fake_rewrite(original, task_type, context, max_tokens, temperature=0.0,
                     rejection_feedback=""):
        calls.append((max_tokens, temperature))
        if len(calls) == 1:
            raise client.Truncated("partial", max_tokens)
        return _mc_item()

    monkeypatch.setattr(backfill, "_rewrite_once", fake_rewrite)
    item = backfill._rewrite_valid(
        {"idx": 0, "reason": "modern", "src": "llm"},
        _task(), {}, 4096, retries=2,
    )
    assert calls == [(4096, 0.0), (8192, 0.0)]
    assert item["gold"] == 1


def test_rejection_feedback_is_in_generation_payload():
    messages = prompts.backfill_messages(
        _mc_item(), "multiple_choice", {"label": "demo"}, "answer is ambiguous"
    )
    payload = json.loads(messages[1]["content"])
    assert payload["rejection_feedback"] == "answer is ambiguous"


def test_offline_commit_copies_complete_preview_verbatim(tmp_path, monkeypatch):
    task = _task()
    pool = [{"idx": 0, "reason": "modern", "src": "llm"}]
    preview = tmp_path / "demo.preview.jsonl"
    raw = json.dumps(_generated(), separators=(",", ":")) + "\n"
    preview.write_text(raw)

    monkeypatch.setattr(backfill, "BACKFILL_DIR", str(tmp_path))
    monkeypatch.setattr(backfill.config, "REVIEW_DIR", str(tmp_path / "review"))
    monkeypatch.setattr(
        backfill,
        "chat_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("commit called API")),
    )
    meta = {
        "demo": {
            "Task Category": "test",
            "Task Type": "multiple choice",
            "#shots": "0",
            "Random baseline": "25",
            "Description": "test benchmark",
        }
    }
    backfill._commit_previews([(task, pool, 1, 0)], meta)
    assert (tmp_path / "demo.jsonl").read_text() == raw


def test_commit_refuses_incomplete_preview(tmp_path, monkeypatch):
    task = _task()
    pool = [{"idx": 0, "reason": "modern", "src": "llm"}]
    (tmp_path / "demo.preview.jsonl").write_text("")
    monkeypatch.setattr(backfill, "BACKFILL_DIR", str(tmp_path))
    with pytest.raises(SystemExit, match="COMMIT REFUSED"):
        backfill._commit_previews([(task, pool, 1, 0)], {})
    assert not (tmp_path / "demo.jsonl").exists()


def test_preview_validation_rejects_duplicate_source_ids():
    task = _task()
    pool = [{"idx": 0, "reason": "modern", "src": "llm"}]
    with pytest.raises(backfill.ValidationError, match="duplicate"):
        backfill._validated_preview(task, pool, 1, [_generated(), _generated()])


def test_rejection_manifest_regenerates_with_feedback_and_higher_temperature(tmp_path, monkeypatch):
    task = _task()
    pool = [{"idx": 0, "reason": "modern", "src": "llm"}]
    monkeypatch.setattr(backfill, "BACKFILL_DIR", str(tmp_path))
    monkeypatch.setattr(backfill.config, "REVIEW_DIR", str(tmp_path / "review"))
    captured = []

    def fake_collect(task, candidates, target, ctx, workers, max_tokens, retries, on_item,
                     generation_options=None):
        source = candidates[0]
        options = generation_options[source["idx"]]
        captured.append(options)
        item = _generated(source["idx"])
        item["generation_revision"] = options["revision"]
        on_item(source, item, 1)
        return 1, []

    monkeypatch.setattr(backfill, "_collect", fake_collect)
    complete, count, _ = backfill._stage_task(
        task, pool, 1, 0, {}, 1, 1, -1, 4, 4096
    )
    assert complete and count == 1
    assert captured[-1]["start_temperature_index"] == 0
    assert captured[-1]["revision"] == 1

    (tmp_path / "demo.rejects.jsonl").write_text(
        json.dumps({"source_idx": 0, "reason": "answer is ambiguous"}) + "\n"
    )
    complete, count, _ = backfill._stage_task(
        task, pool, 1, 0, {}, 1, 1, -1, 4, 4096
    )
    assert complete and count == 1
    assert captured[-1]["start_temperature_index"] == 1
    assert captured[-1]["rejection_feedback"] == "answer is ambiguous"
    assert captured[-1]["revision"] == 2
    assert (tmp_path / "demo.rejects.jsonl").read_text() == ""
