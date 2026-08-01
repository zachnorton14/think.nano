import json
from types import SimpleNamespace

import pytest

from dev.vintage_gsm8k import pipeline, publication, reviewer
from dev.vintage_gsm8k.client import APIError, FreeUsageLimitError
from dev.vintage_gsm8k.config import (
    JUDGE_MODEL,
    JUDGE_PROMPT_VERSION,
    NORMALIZATION_VERSION,
    REWRITE_FREE_ENDPOINT,
    REWRITE_FREE_MODEL,
    REWRITE_MODEL,
    REWRITE_PAID_ENDPOINT,
    REWRITE_PAID_MODEL,
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
    read_jsonl,
    read_latest_by_id,
    stable_hash,
    validate_candidate,
)
from dev.vintage_gsm8k.prompts import JUDGE_SYSTEM_PROMPT
from dev.vintage_gsm8k.prefilter import scan_rows
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


def judge_record(row, action="keep", reason="All concepts predate 1931", model=JUDGE_MODEL):
    return {
        "id": row["id"],
        "split": row["split"],
        "index": row["index"],
        "action": action,
        "reason": reason,
        "source_hash": row["source_hash"],
        "prompt_version": JUDGE_PROMPT_VERSION,
        "model": model,
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
        self.chat_requests = []
        self.response_calls = 0

    def chat_json(self, **kwargs):
        self.chat_calls += 1
        self.chat_requests.append(kwargs)
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
        "A total is <<1,200+300=1500>>1,500. Groups are <<560//10=56>>56.\n#### -1,500"
    )
    calculations = parse_calculator_annotations(answer)
    assert [item["valid"] for item in calculations] == [True, True, True, True]
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
    text = "$2000 buys 2,000 objects over 1955 kilometers and in 4500 seconds. In 2021, one changed."
    assert contextual_years(text) == [2021]
    assert post_cutoff_years(text) == [2021]
    assert post_cutoff_years("The relic was dated 8400 BC.") == []


def test_tiered_regex_prefilter_handles_inflections_and_policy():
    tiers = {"dvd": 1, "video game": 2, "download": 3, "website": "strip"}
    questions = [
        "Ada owns 3 DVDs.",
        "Ada downloads 3 files.",
        "Ada downloads a video game.",
        "Ada visits a website.",
        "In 2021 Ada owned 3 books.",
        "Ada carries $2000 for 1955 kilometers.",
    ]
    rows = [source_row(index=index, question=question) for index, question in enumerate(questions)]
    actions = [row["action"] for row in scan_rows(rows, tiers)]
    assert actions == ["flag", "clear", "flag", "clear", "flag", "clear"]
    assert scan_rows(rows, tiers)[0]["hits"][0]["term"] == "dvd"


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


def test_api_transport_error_does_not_bisect_batch():
    rows = [source_row(index=0), source_row(index=1)]
    client = QueueClient(chat=[APIError("HTTP 403")])
    verdicts, calls = pipeline._judge_with_recovery(rows, client, 1024)
    assert [row["action"] for row in verdicts] == ["error", "error"]
    assert client.chat_calls == 1
    assert len(calls) == 1


def test_free_usage_limit_stops_unscheduled_batches(tmp_path, monkeypatch):
    paths = PipelinePaths(tmp_path)
    train = [source_row(index=index) for index in range(3)]
    test = [source_row("test")]
    make_snapshot(paths, train, test)
    monkeypatch.setattr(pipeline, "prepare", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        pipeline,
        "run_prefilter",
        lambda active_paths: atomic_write_json(active_paths.regex_manifest, {"splits": {}}),
    )
    client = QueueClient(chat=[FreeUsageLimitError("free allowance exhausted")])

    result = pipeline.judge(paths, batch_size=1, workers=1, client=client)

    assert result["halted"] == "free_usage_limit"
    assert client.chat_calls == 1
    assert len(read_latest_by_id(paths.judge("train"))) == 1


def test_paid_judge_reuses_valid_free_alias_verdict(tmp_path, monkeypatch):
    paths = PipelinePaths(tmp_path)
    train, test = source_row("train"), source_row("test")
    make_snapshot(paths, [train], [test])
    atomic_write_jsonl(
        paths.judge("train"),
        [judge_record(train, model="deepseek-v4-flash-free")],
    )
    atomic_write_jsonl(paths.judge("test"), [judge_record(test)])
    atomic_write_json(paths.regex_manifest, {"splits": {}})
    monkeypatch.setattr(pipeline, "prepare", lambda *args, **kwargs: {})
    client = QueueClient()

    result = pipeline.judge(paths, batch_size=1, workers=1, client=client)

    assert JUDGE_MODEL == "deepseek-v4-flash"
    assert client.chat_calls == 0
    assert result["splits"]["train"]["judged"] == 1


def test_paid_judge_retries_free_alias_error(tmp_path, monkeypatch):
    paths = PipelinePaths(tmp_path)
    train, test = source_row("train"), source_row("test")
    make_snapshot(paths, [train], [test])
    atomic_write_jsonl(
        paths.judge("train"),
        [judge_record(train, action="error", reason="free limit", model="deepseek-v4-flash-free")],
    )
    atomic_write_jsonl(paths.judge("test"), [judge_record(test)])
    atomic_write_json(paths.regex_manifest, {"splits": {}})
    monkeypatch.setattr(pipeline, "prepare", lambda *args, **kwargs: {})
    client = QueueClient(chat=[[{"id": train["id"], "action": "keep", "reason": "ok"}]])

    pipeline.judge(paths, batch_size=1, workers=1, client=client)

    latest = read_latest_by_id(paths.judge("train"))[train["id"]]
    assert client.chat_calls == 1
    assert latest["action"] == "keep"
    assert latest["model"] == "deepseek-v4-flash"


def test_paid_judge_invalidates_unrelated_model_family(tmp_path, monkeypatch):
    paths = PipelinePaths(tmp_path)
    train, test = source_row("train"), source_row("test")
    make_snapshot(paths, [train], [test])
    atomic_write_jsonl(paths.judge("train"), [judge_record(train, model="unrelated-model")])
    atomic_write_jsonl(paths.judge("test"), [judge_record(test, model="unrelated-model")])
    atomic_write_json(paths.regex_manifest, {"splits": {}})
    monkeypatch.setattr(pipeline, "prepare", lambda *args, **kwargs: {})
    client = QueueClient(
        chat=[
            [{"id": train["id"], "action": "keep", "reason": "ok"}],
            [{"id": test["id"], "action": "keep", "reason": "ok"}],
        ]
    )

    pipeline.judge(paths, batch_size=1, workers=1, client=client)

    assert client.chat_calls == 2


def test_judge_resume_and_prompt_invalidation(tmp_path, monkeypatch):
    paths = PipelinePaths(tmp_path)
    train, test = source_row("train"), source_row("test", question="Ben has 2 pears and gets 3 more.")
    make_snapshot(paths, [train], [test])
    monkeypatch.setattr(pipeline, "prepare", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        pipeline,
        "run_prefilter",
        lambda active_paths: atomic_write_json(active_paths.regex_manifest, {"splits": {}}),
    )
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
    monkeypatch.setattr(
        pipeline,
        "run_prefilter",
        lambda active_paths: atomic_write_json(active_paths.regex_manifest, {"splits": {}}),
    )
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
    assert attempts[-1]["terminal_reason"] == "validation_exhaustion"
    assert client.chat_calls == 3


def test_rewrite_api_error_is_resumable_not_manual():
    row = source_row(question="Ada downloads 2 files and then 3 more. How many?")
    client = QueueClient(chat=[APIError("temporary transport failure")])
    attempts, _ = pipeline._rewrite_one(
        row,
        {"mode": "surface", "reason": "downloads", "judge_reason": "downloads"},
        client,
        3,
    )
    assert len(attempts) == 1
    assert attempts[-1]["status"] == "error"
    assert attempts[-1]["error_type"] == "api"
    assert client.chat_calls == 1


def test_rewrite_retries_legacy_api_manual_but_keeps_validation_manual(tmp_path, monkeypatch):
    paths = PipelinePaths(tmp_path)
    transport = source_row(index=0, question="Ada downloads 2 files and gets 3 more. How many?")
    validation = source_row(index=1, question="Ben downloads 3 files and gets 3 more. How many?")
    test = [source_row("test")]
    make_snapshot(paths, [transport, validation], test)
    atomic_write_jsonl(
        paths.judge("train"),
        [judge_record(transport, action="rewrite"), judge_record(validation, action="rewrite")],
    )
    atomic_write_jsonl(paths.judge("test"), [judge_record(test[0])])
    decisions = [
        {
            "id": row["id"],
            "source_hash": row["source_hash"],
            "judge_prompt_version": JUDGE_PROMPT_VERSION,
            "decision": "rewrite",
            "reason": "downloads are post-cutoff",
            "mode": "surface",
        }
        for row in (transport, validation)
    ]
    atomic_write_jsonl(paths.decisions, decisions)

    def common(row, decision):
        return {
            "id": row["id"],
            "source_hash": row["source_hash"],
            "decision_hash": stable_hash(
                {key: decision[key] for key in ("decision", "reason", "mode")}
            ),
            "prompt_version": REWRITE_PROMPT_VERSION,
            "model": REWRITE_FREE_MODEL,
            "accepted": False,
        }

    transport_common = common(transport, decisions[0])
    validation_common = common(validation, decisions[1])
    atomic_write_jsonl(
        paths.rewrites("train"),
        [
            {**transport_common, "error_type": "api", "status": "error"},
            {**transport_common, "status": "manual"},
            {**validation_common, "candidate": {}, "errors": ["bad candidate"]},
            {**validation_common, "status": "manual"},
        ],
    )
    candidate = {
        "question": transport["question"].replace("downloads", "receives"),
        "answer": transport["answer"],
        "calculations": [
            {"expression": item["expression"], "result": item["result"]}
            for item in transport["calculations"]
        ],
    }
    client = QueueClient(chat=[candidate])
    monkeypatch.setattr(pipeline, "_require_full_judge", lambda *args, **kwargs: None)

    pipeline.rewrite(paths, workers=1, client=client)

    latest = read_latest_by_id(paths.rewrites("train"))
    assert latest[transport["id"]]["accepted"] is True
    assert latest[validation["id"]]["status"] == "manual"
    assert client.chat_calls == 1


def test_apply_manual_rewrites_validates_exact_gate_and_appends_acceptance(tmp_path):
    paths = PipelinePaths(tmp_path)
    row = source_row(question="Ada downloads 2 files and gets 3 more. How many?")
    test = source_row("test")
    make_snapshot(paths, [row], [test])
    atomic_write_jsonl(
        paths.decisions,
        [
            {
                "id": row["id"],
                "source_hash": row["source_hash"],
                "decision": "rewrite",
                "reason": "downloads are post-cutoff",
                "mode": "surface",
            }
        ],
    )
    atomic_write_jsonl(
        paths.rewrites("train"),
        [{"id": row["id"], "accepted": False, "status": "manual"}],
    )
    manual_path = paths.review_dir / "manual-rewrites.jsonl"
    atomic_write_jsonl(
        manual_path,
        [
            {
                "id": row["id"],
                "question": row["question"].replace("downloads", "receives"),
                "answer": row["answer"],
                "calculations": [
                    {"expression": item["expression"], "result": item["result"]}
                    for item in row["calculations"]
                ],
                "reason": "Preserved the MiMo arithmetic while replacing the modern carrier.",
                "base_attempt": 3,
            }
        ],
    )

    result = reviewer.apply_manual_rewrites(paths, manual_path)

    latest = read_latest_by_id(paths.rewrites("train"))[row["id"]]
    assert result["accepted"] == 1
    assert latest["accepted"] is True
    assert latest["status"] == "manual_accepted"
    assert latest["model"] == "manual-review"


def test_rewrite_reuses_free_success_and_falls_back_to_paid(tmp_path, monkeypatch):
    paths = PipelinePaths(tmp_path)
    train = [
        source_row(index=index, question=f"Ada downloads {index + 2} files and gets 3 more. How many?")
        for index in range(2)
    ]
    test = [source_row("test")]
    make_snapshot(paths, train, test)
    atomic_write_jsonl(paths.judge("train"), [judge_record(row, action="rewrite") for row in train])
    atomic_write_jsonl(paths.judge("test"), [judge_record(test[0])])
    atomic_write_jsonl(
        paths.decisions,
        [
            {
                "id": row["id"],
                "source_hash": row["source_hash"],
                "judge_prompt_version": JUDGE_PROMPT_VERSION,
                "decision": "rewrite",
                "reason": "downloads are post-cutoff",
                "mode": "surface",
            }
            for row in train
        ],
    )
    candidates = [
        {
            "question": row["question"].replace("downloads", "receives"),
            "answer": row["answer"],
            "calculations": [
                {"expression": item["expression"], "result": item["result"]}
                for item in row["calculations"]
            ],
        }
        for row in train
    ]
    client = QueueClient(chat=[candidates[0], FreeUsageLimitError("free limit"), candidates[1]])
    monkeypatch.setattr(pipeline, "_require_full_judge", lambda *args, **kwargs: None)

    result = pipeline.rewrite(paths, workers=1, max_attempts=3, client=client)

    latest = read_latest_by_id(paths.rewrites("train"))
    assert result.get("halted") is None
    assert latest[train[0]["id"]]["model"] == REWRITE_FREE_MODEL
    assert latest[train[1]["id"]]["model"] == REWRITE_PAID_MODEL
    assert [request["model"] for request in client.chat_requests] == [
        REWRITE_FREE_MODEL,
        REWRITE_FREE_MODEL,
        REWRITE_PAID_MODEL,
    ]
    assert [request["endpoint"] for request in client.chat_requests] == [
        REWRITE_FREE_ENDPOINT,
        REWRITE_FREE_ENDPOINT,
        REWRITE_PAID_ENDPOINT,
    ]


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


def test_stage_publications_builds_filtered_and_full_variants(tmp_path, monkeypatch):
    paths = PipelinePaths(tmp_path)
    keep = source_row(index=0)
    flagged = source_row(index=1, question="Ada downloads 2 files and gets 3 more. How many?")
    test = source_row("test")
    make_snapshot(paths, [keep, flagged], [test])
    atomic_write_jsonl(
        paths.judge("train"),
        [judge_record(keep), judge_record(flagged, action="rewrite")],
    )
    atomic_write_jsonl(paths.judge("test"), [judge_record(test)])
    atomic_write_jsonl(
        paths.decisions,
        [
            {
                "id": flagged["id"],
                "source_hash": flagged["source_hash"],
                "judge_prompt_version": JUDGE_PROMPT_VERSION,
                "decision": "rewrite",
                "reason": "downloads are post-cutoff",
                "mode": "surface",
            }
        ],
    )
    atomic_write_jsonl(
        paths.packaged("train"),
        [
            {key: row[key] for key in ("id", "question", "answer")}
            for row in (keep, flagged)
        ],
    )
    atomic_write_jsonl(
        paths.packaged("test"),
        [{key: test[key] for key in ("id", "question", "answer")}],
    )
    monkeypatch.setattr(publication, "_require_full_judge", lambda *args, **kwargs: None)
    monkeypatch.setattr(publication, "EXPECTED_COUNTS", {"train": 2, "test": 1})

    result = publication.stage_publications(paths)

    assert result["filtered"]["counts"] == {"train": 1, "test": 1}
    assert result["rewritten"]["counts"] == {"train": 2, "test": 1}
    assert len(read_jsonl(paths.root / "publish" / "filtered" / "data" / "train.jsonl")) == 1
    card = (paths.root / "publish" / "rewritten" / "README.md").read_text()
    assert "license: mit" in card
    assert "# Vintage GSM8K" in card


def test_apply_subagent_review_requires_exact_coverage(tmp_path):
    paths = PipelinePaths(tmp_path)
    rows = [source_row(index=index) for index in range(2)]
    atomic_write_jsonl(
        paths.decisions,
        [
            {
                "id": row["id"],
                "decision": None,
                "reason": "",
                "mode": "surface",
            }
            for row in rows
        ],
    )
    proposal = paths.review_dir / "subagent-review.jsonl"
    atomic_write_jsonl(
        proposal,
        [
            {
                "id": rows[0]["id"],
                "proposed_decision": "rewrite",
                "reason": "modern context",
                "risk_tags": ["technology"],
            },
            {
                "id": rows[1]["id"],
                "proposed_decision": "keep",
                "reason": "available by 1930",
                "risk_tags": [],
            },
        ],
    )
    atomic_write_jsonl(
        paths.review_dir / "reviewer-overrides.jsonl",
        [
            {
                "id": rows[1]["id"],
                "decision": "rewrite",
                "reason": "conservative human override",
                "mode": "date",
            }
        ],
    )
    result = reviewer.apply_subagent_review(paths, proposal)
    assert result["counts"] == {"rewrite": 2}
    merged = read_jsonl(paths.decisions)
    assert merged[0]["reviewed_by"] == "artifact-review-subagent"
    assert merged[1]["reviewed_by"] == "human-review-override"
    assert merged[1]["mode"] == "date"

    atomic_write_jsonl(proposal, [read_jsonl(proposal)[0]])
    with pytest.raises(RuntimeError, match="missing=1"):
        reviewer.apply_subagent_review(paths, proposal)


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
