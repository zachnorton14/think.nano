import json
from types import SimpleNamespace

import pytest

from dev.vintage_gsm8k import pipeline
from dev.vintage_gsm8k.config import (
    JUDGE_MODEL,
    JUDGE_PROMPT_VERSION,
    NORMALIZATION_VERSION,
    REWRITE_MODEL,
    REWRITE_PROMPT_VERSION,
    PipelinePaths,
)
from dev.vintage_gsm8k.data import (
    answers_equal,
    atomic_write_json,
    atomic_write_jsonl,
    contextual_years,
    extract_final_answer,
    normalize_answer,
    parse_calculator_annotations,
    post_cutoff_years,
    stable_hash,
    validate_candidate,
)
from dev.vintage_gsm8k.prompts import JUDGE_SYSTEM_PROMPT
from nanochat.tokenizer import RustBPETokenizer
from tasks.gsm8k import GSM8K


def source_row(split="train", index=0, question="Ada has 2 apples and gets 3 more. How many?"):
    raw_answer = "Ada adds 2+3 = <<2+3=5>>5.\n#### 5"
    row_id = f"gsm8k-main-{split}-{index:06d}"
    return {
        "id": row_id,
        "split": split,
        "index": index,
        "question": question,
        "answer": normalize_answer(raw_answer),
        "raw_answer": raw_answer,
        "calculations": parse_calculator_annotations(raw_answer),
        "source_hash": stable_hash({"id": row_id, "raw": raw_answer}),
    }


def judge_record(row, action="keep", reason="All concepts predate 1931"):
    return {
        "id": row["id"],
        "split": row["split"],
        "index": row["index"],
        "action": action,
        "reason": reason,
        "source_hash": row["source_hash"],
        "prompt_version": JUDGE_PROMPT_VERSION,
        "model": JUDGE_MODEL,
    }


def make_snapshot(paths, train_rows, test_rows):
    atomic_write_jsonl(paths.source("train"), train_rows)
    atomic_write_jsonl(paths.source("test"), test_rows)
    atomic_write_json(
        paths.manifest,
        {
            "normalization_version": NORMALIZATION_VERSION,
            "split_counts": {"train": len(train_rows), "test": len(test_rows)},
        },
    )


class QueueClient:
    def __init__(self, chat=None, responses=None):
        self.chat = list(chat or [])
        self.responses = list(responses or [])
        self.chat_calls = 0
        self.response_calls = 0

    def chat_json(self, **kwargs):
        self.chat_calls += 1
        value = self.chat.pop(0)
        if isinstance(value, Exception):
            raise value
        return value, {"model": kwargs["model"], "prompt_tokens": 1, "completion_tokens": 1}

    def responses_json(self, **kwargs):
        self.response_calls += 1
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value, {"model": kwargs["model"], "prompt_tokens": 1, "completion_tokens": 1}


def test_prepare_resolves_revision_and_never_replaces_snapshot(tmp_path, monkeypatch):
    import datasets
    import huggingface_hub

    paths = PipelinePaths(tmp_path)
    calls = []

    class FakeDataset(list):
        _fingerprint = "fake-fingerprint"

    def fake_load_dataset(dataset_id, subset, split, revision):
        calls.append((dataset_id, subset, split, revision))
        name = "Ada" if split == "train" else "Ben"
        return FakeDataset(
            [{"question": f"{name} has 2 items and gets 3 more.", "answer": f"{name} adds 2+3 = <<2+3=5>>5.\n#### 5"}]
        )

    class FakeApi:
        def dataset_info(self, dataset_id, revision):
            assert dataset_id == "openai/gsm8k"
            assert revision == "main"
            return SimpleNamespace(sha="resolved-sha")

    monkeypatch.setattr(datasets, "load_dataset", fake_load_dataset)
    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)
    monkeypatch.setattr(pipeline, "EXPECTED_COUNTS", {"train": 1, "test": 1})
    manifest = pipeline.prepare(paths)
    assert manifest["resolved_revision"] == "resolved-sha"
    assert manifest["dataset_fingerprint"]
    assert all(call[-1] == "resolved-sha" for call in calls)
    prepared_row = json.loads(paths.source("train").read_text())
    assert "<<" not in prepared_row["answer"]
    assert "<<2+3=5>>" in prepared_row["raw_answer"]

    before = paths.source("train").read_bytes()
    pipeline.prepare(paths)
    assert paths.source("train").read_bytes() == before
    assert len(calls) == 2

def test_annotation_removal_and_arithmetic_variants():
    answer = (
        "Half is <<3/4=3/4>>3/4. A debt is <<-2*3=-6>>-6. "
        "A total is <<1,200+300=1500>>1,500.\n#### -1,500"
    )
    calculations = parse_calculator_annotations(answer)
    assert [item["valid"] for item in calculations] == [True, True, True]
    assert calculations[0]["result"] == "3/4"
    assert "<<" not in normalize_answer(answer)
    assert "3/4" in normalize_answer(answer)
    assert extract_final_answer(answer) == "-1500"
    assert answers_equal("3/4", "0.75")


def test_final_answer_requires_exactly_one_parseable_marker():
    assert extract_final_answer("work\n#### -2.5") == "-2.5"
    assert extract_final_answer("#### 2\n#### 3") is None
    assert extract_final_answer("#### bananas") is None


def test_contextual_years_do_not_treat_quantities_as_dates():
    text = "$2000 buys 2,000 objects over 1955 kilometers. In 2021, one changed."
    assert contextual_years(text) == [2021]
    assert post_cutoff_years(text) == [2021]


def test_judge_prompt_covers_inflections_and_conceptual_misses():
    assert "DVDs" in JUDGE_SYSTEM_PROMPT
    assert "iPhones" in JUDGE_SYSTEM_PROMPT
    assert "downloads" in JUDGE_SYSTEM_PROMPT
    assert "websites" in JUDGE_SYSTEM_PROMPT
    assert "Inspect both question and solution" in JUDGE_SYSTEM_PROMPT


def test_malformed_batch_retries_then_bisects():
    rows = [source_row(index=0), source_row(index=1)]
    client = QueueClient(
        chat=[
            {"not": "an array"},
            [{"id": rows[0]["id"], "action": "keep", "reason": "ok"}],
            [{"id": rows[0]["id"], "action": "keep", "reason": "ok"}],
            [{"id": rows[1]["id"], "action": "keep", "reason": "ok"}],
        ]
    )
    verdicts, calls = pipeline._judge_with_recovery(rows, client, 1024)
    assert [row["id"] for row in verdicts] == [row["id"] for row in rows]
    assert all(row["action"] == "keep" for row in verdicts)
    assert len(calls) == 4


def test_duplicate_ids_fail_closed_to_error():
    row = source_row()
    duplicate = [
        {"id": row["id"], "action": "keep", "reason": "ok"},
        {"id": row["id"], "action": "keep", "reason": "ok"},
    ]
    client = QueueClient(chat=[duplicate, duplicate])
    verdicts, _ = pipeline._judge_with_recovery([row], client, 1024)
    assert verdicts[0]["action"] == "error"
    assert "duplicate" in verdicts[0]["reason"]


def test_judge_resume_and_prompt_invalidation(tmp_path, monkeypatch):
    paths = PipelinePaths(tmp_path)
    train, test = source_row("train"), source_row("test", question="Ben has 2 pears and gets 3 more.")
    make_snapshot(paths, [train], [test])
    monkeypatch.setattr(pipeline, "prepare", lambda *args, **kwargs: {})
    client = QueueClient(
        chat=[
            [{"id": train["id"], "action": "keep", "reason": "ok"}],
            [{"id": test["id"], "action": "keep", "reason": "ok"}],
        ]
    )
    pipeline.judge(paths, batch_size=1, workers=1, client=client)
    assert client.chat_calls == 2
    pipeline.judge(paths, batch_size=1, workers=1, client=client)
    assert client.chat_calls == 2

    monkeypatch.setattr(pipeline, "JUDGE_PROMPT_VERSION", "judge-v-next")
    client.chat.extend(
        [
            [{"id": train["id"], "action": "keep", "reason": "ok"}],
            [{"id": test["id"], "action": "keep", "reason": "ok"}],
        ]
    )
    pipeline.judge(paths, batch_size=1, workers=1, client=client)
    assert client.chat_calls == 4


def test_api_error_is_fail_closed_and_resumable(tmp_path, monkeypatch):
    paths = PipelinePaths(tmp_path)
    train, test = source_row("train"), source_row("test", question="Ben has 2 pears and gets 3 more.")
    make_snapshot(paths, [train], [test])
    monkeypatch.setattr(pipeline, "prepare", lambda *args, **kwargs: {})
    failed = QueueClient(chat=[RuntimeError("offline")] * 4)
    first = pipeline.judge(paths, batch_size=1, workers=1, client=failed)
    assert first["splits"]["train"]["errors"] == 1
    assert first["splits"]["test"]["errors"] == 1
    assert first["splits"]["train"]["judged"] == 0

    recovered = QueueClient(
        chat=[
            [{"id": train["id"], "action": "keep", "reason": "ok"}],
            [{"id": test["id"], "action": "keep", "reason": "ok"}],
        ]
    )
    second = pipeline.judge(paths, batch_size=1, workers=1, client=recovered)
    assert second["splits"]["train"]["judged"] == 1
    assert second["splits"]["test"]["judged"] == 1
    assert second["splits"]["train"]["errors"] == 0


def test_surface_and_date_candidate_invariants():
    surface = source_row()
    calculations = [{"expression": "2+3", "result": "5"}]
    good = {"question": surface["question"], "answer": surface["answer"], "calculations": calculations}
    assert validate_candidate(surface, good, "surface") == []
    changed_number = {**good, "question": surface["question"].replace("2", "4")}
    assert any("numeric literals" in error for error in validate_candidate(surface, changed_number, "surface"))

    dated = source_row(question="In 2021, Ada had 2 apples and got 3 more. How many?")
    date_candidate = {
        "question": "In 1921, Ada had 2 apples and got 3 more. How many?",
        "answer": dated["answer"],
        "calculations": calculations,
    }
    assert validate_candidate(dated, date_candidate, "date") == []
    date_candidate["question"] = "In 2020, Ada had 2 apples and got 3 more. How many?"
    assert any("post-1930" in error for error in validate_candidate(dated, date_candidate, "date"))


def test_rewrite_retry_exhaustion_routes_to_manual():
    row = source_row(question="Ada downloads 2 files and then 3 more. How many?")
    bad = {"question": "Ada downloads 4 files.", "answer": "#### 4", "calculations": []}
    client = QueueClient(chat=[bad, bad, bad])
    attempts, _ = pipeline._rewrite_one(
        row,
        {"mode": "surface", "reason": "downloads", "judge_reason": "downloads"},
        client,
        3,
    )
    assert attempts[-1]["status"] == "manual"
    assert client.chat_calls == 3


def test_solver_disagreement_and_temporal_rejection():
    source = source_row()
    row = {
        **source,
        "candidate_hash": "candidate",
        "changed": True,
        "mode": "surface",
        "calculations": [{"expression": "2+3", "result": "5"}],
    }
    wrong_solver = QueueClient(responses=[{"answer": "6"}])
    result, _ = pipeline._verify_one(row, source, wrong_solver)
    assert not result["accepted"]
    assert "disagrees" in result["errors"][0]
    assert wrong_solver.chat_calls == 0

    temporal_reject = QueueClient(
        responses=[{"answer": "5"}],
        chat=[[{"id": source["id"], "action": "rewrite", "reason": "modern context"}]],
    )
    result, _ = pipeline._verify_one(row, source, temporal_reject)
    assert not result["accepted"]
    assert result["temporal_action"] == "rewrite"


def test_vintage_task_uses_plain_string_and_renders(tmp_path):
    rows = [{"id": "gsm8k-main-test-000000", "question": "What is 2+3?", "answer": "2+3=5.\n#### 5"}]
    atomic_write_jsonl(tmp_path / "test.jsonl", rows)
    task = GSM8K(subset="main", split="test", variant="vintage", data_dir=tmp_path)
    conversation = task[0]
    assert isinstance(conversation["messages"][-1]["content"], str)

    class TinyVintageTokenizer:
        render_conversation = RustBPETokenizer.render_conversation

        def get_bos_token_id(self):
            return 0

        def encode_special(self, text):
            return {"<|user_start|>": 1, "<|user_end|>": 2, "<|assistant_start|>": 3, "<|assistant_end|>": 4}[text]

        def encode(self, text):
            return list(text.encode("utf-8"))

    ids, mask = TinyVintageTokenizer().render_conversation(conversation)
    assert len(ids) == len(mask)
    assert any(mask)
    assert task.evaluate(conversation, "work\n#### 5") == 1
    assert task.evaluate(conversation, [{"type": "text", "text": "#### 5"}]) == 1


def test_small_end_to_end_package_preserves_ids_order_and_raw_test(tmp_path, monkeypatch):
    paths = PipelinePaths(tmp_path)
    train = source_row("train")
    test = source_row("test", question="Ben has 7 pears and loses 2. How many?")
    test_raw = "Ben subtracts 7-2 = <<7-2=5>>5.\n#### 5"
    test.update(
        raw_answer=test_raw,
        answer=normalize_answer(test_raw),
        calculations=parse_calculator_annotations(test_raw),
    )
    make_snapshot(paths, [train], [test])
    atomic_write_jsonl(paths.judge("train"), [judge_record(train)])
    atomic_write_jsonl(paths.judge("test"), [judge_record(test)])
    atomic_write_jsonl(paths.decisions, [])
    monkeypatch.setattr(pipeline, "EXPECTED_COUNTS", {"train": 1, "test": 1})
    result = pipeline.package(paths)
    assert result["counts"] == {"train": 1, "test": 1}
    packaged = [json.loads(line) for line in paths.packaged("test").read_text().splitlines()]
    assert list(packaged[0]) == ["answer", "id", "question"]  # deterministic JSONL key sorting
    assert packaged[0]["id"] == "gsm8k-main-test-000000"
    assert "<<" not in packaged[0]["answer"]
    assert "<<7-2=5>>" in (paths.data_dir / "test.raw.jsonl").read_text()


def test_review_gate_requires_decision_and_reason(tmp_path, monkeypatch):
    paths = PipelinePaths(tmp_path)
    train = source_row("train", question="Ada downloads 2 files and gets 3 more.")
    test = source_row("test", question="Ben has 2 pears and gets 3 more.")
    make_snapshot(paths, [train], [test])
    atomic_write_jsonl(paths.judge("train"), [judge_record(train, "rewrite", "downloads are modern")])
    atomic_write_jsonl(paths.judge("test"), [judge_record(test)])
    monkeypatch.setattr(pipeline, "EXPECTED_COUNTS", {"train": 1, "test": 1})
    pipeline.report(paths)
    with pytest.raises(RuntimeError, match="Review gate is incomplete"):
        pipeline.package(paths)
    decision = json.loads(paths.decisions.read_text())
    decision.update(decision="rewrite", reason="replace downloads", mode="surface")
    atomic_write_jsonl(paths.decisions, [decision])
    with pytest.raises(RuntimeError, match="no accepted candidate"):
        pipeline.package(paths)
