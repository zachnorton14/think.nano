import math

import pytest
import torch

from dev.history_event.bpb import (
    aggregate_scores,
    hf_target_tokens,
    metrics_from_logits,
    native_target_tokens,
    tiktoken_target_tokens,
)
from dev.history_event.io import iter_jsonl, write_jsonl
from dev.history_event.scoring import score_events


class FakeEncoding:
    def __init__(self, pieces):
        self.pieces = pieces

    def decode_single_token_bytes(self, token_id):
        return self.pieces[token_id]


class FakeNativeTokenizer:
    def __init__(self, pieces):
        self.enc = FakeEncoding(pieces)

    def encode(self, text):
        assert text == "A é"
        return [0, 1, 2]

    def get_bos_token_id(self):
        return 99


class FakeHFTokenizer:
    bos_token_id = 99
    eos_token_id = None

    def __init__(self, offsets):
        self.offsets = offsets

    def __call__(self, text, **kwargs):
        assert text == "A é"
        return {"input_ids": list(range(len(self.offsets))), "offset_mapping": self.offsets}


class FakeTiktokenTokenizer:
    pieces = {0: b"A", 1: b" \xc3", 2: b"\xa9"}

    def encode(self, text):
        assert text == "A é"
        return [0, 1, 2]

    def decode_single_token_bytes(self, token_id):
        return self.pieces[token_id]


def test_native_utf8_mask_records_boundary_crossing_token():
    tokenizer = FakeNativeTokenizer({0: b"A", 1: b" \xc3", 2: b"\xa9"})
    tokens = native_target_tokens(tokenizer, "A", "é")
    assert tokens.input_ids == [99, 0, 1, 2]
    assert tokens.target_mask == [False, True, True]
    assert tokens.target_bytes == 2
    assert tokens.boundary_crossing == [{
        "token_index": 2, "token_id": 1, "start_byte": 1, "end_byte": 3
    }]


def test_hf_offsets_handle_leading_space_and_boundary_crossing():
    crossing = hf_target_tokens(FakeHFTokenizer([(0, 1), (1, 3)]), "A", "é")
    assert crossing.target_mask == [False, True]
    assert crossing.target_bytes == 2
    assert crossing.boundary_crossing[0]["start_character"] == 1
    separate = hf_target_tokens(FakeHFTokenizer([(0, 1), (1, 2), (2, 3)]), "A", "é")
    assert separate.target_mask == [False, False, True]
    assert separate.boundary_crossing == []


def test_raw_tiktoken_mask_uses_explicit_model_bos():
    tokens = tiktoken_target_tokens(FakeTiktokenTokenizer(), "A", "é", 99)
    assert tokens.input_ids == [99, 0, 1, 2]
    assert tokens.target_mask == [False, True, True]
    assert tokens.target_bytes == 2
    assert tokens.boundary_crossing == [{
        "token_index": 2, "token_id": 1, "start_byte": 1, "end_byte": 3,
    }]


def test_target_masked_bpb_matches_hand_computed_toy_logits():
    logits = torch.zeros((3, 2), dtype=torch.float32)
    metrics = metrics_from_logits(logits, [0, 1, 0], [False, True, True], target_bytes=2)
    assert metrics["nll_nats"] == pytest.approx(2 * math.log(2))
    assert metrics["bpb"] == pytest.approx(1.0)
    assert metrics["target_token_count"] == 2


def test_decade_macro_micro_std_error_and_cutoff_summaries():
    rows = [
        {"event_year": 1900, "event_decade": 1900, "bpb": 1.0, "nll_nats": math.log(2), "target_bytes": 1},
        {"event_year": 1901, "event_decade": 1900, "bpb": 3.0, "nll_nats": 6 * math.log(2), "target_bytes": 2},
        {"event_year": 1910, "event_decade": 1910, "bpb": 2.0, "nll_nats": 2 * math.log(2), "target_bytes": 1},
    ]
    summary = aggregate_scores(rows, cutoff_year=1900)
    assert summary["by_decade"]["1900"]["macro_mean_bpb"] == 2.0
    assert summary["by_decade"]["1900"]["micro_bpb"] == pytest.approx(7 / 3)
    assert summary["by_decade"]["1900"]["standard_deviation"] == 1.0
    assert summary["by_decade"]["1900"]["standard_error"] == pytest.approx(1 / math.sqrt(2))
    assert summary["pre_cutoff"]["event_count"] == 1
    assert summary["post_cutoff"]["event_count"] == 2
    no_cutoff = aggregate_scores(rows, cutoff_year=None)
    assert no_cutoff["overall"]["event_count"] == 3
    assert no_cutoff["pre_cutoff"] is None
    assert no_cutoff["post_cutoff"] is None


class FakeAdapter:
    def __init__(self, fail_target=None):
        self.fail_target = fail_target
        self.calls = []

    def score(self, prefix, target):
        self.calls.append(target)
        if target == self.fail_target:
            raise RuntimeError("temporary")
        return {
            "nll_nats": math.log(2), "target_bytes": 1,
            "target_token_count": 1, "bpb": 1.0, "boundary_crossing": [],
        }


def test_scoring_is_resumable_and_retries_only_errors(tmp_path):
    events = [
        {
            "id": f"history-event-{index:06d}", "event_year": 1900 + index,
            "event_decade": 1900, "source_hash": f"hash-{index}",
            "bpb_prefix": "prefix", "bpb_target": f"target-{index}",
        }
        for index in range(2)
    ]
    events_path = tmp_path / "source.jsonl"
    output = tmp_path / "results"
    write_jsonl(events_path, events)
    first = FakeAdapter(fail_target="target-1")
    result = score_events(
        model_id="gpt1900-d34", events_path=events_path, output_dir=output,
        cache_dir=tmp_path / "cache", adapter=first,
    )
    assert result["events_scored"] == 1
    assert result["unresolved_errors"] == 1
    second = FakeAdapter()
    result = score_events(
        model_id="gpt1900-d34", events_path=events_path, output_dir=output,
        cache_dir=tmp_path / "cache", adapter=second,
    )
    assert second.calls == ["target-1"]
    assert result["complete"] is True
    latest_rows = list(iter_jsonl(output / "events.jsonl"))
    assert len(latest_rows) == 3  # append-only: one success, one error, one retry


def test_scoring_first_row_gate_avoids_repeating_systemic_errors(tmp_path):
    events = [
        {
            "id": f"history-event-{index:06d}", "event_year": 1900 + index,
            "event_decade": 1900, "source_hash": f"hash-{index}",
            "bpb_prefix": "prefix", "bpb_target": f"target-{index}",
        }
        for index in range(2)
    ]
    events_path = tmp_path / "source.jsonl"
    write_jsonl(events_path, events)
    adapter = FakeAdapter(fail_target="target-0")
    result = score_events(
        model_id="gpt1900-d34", events_path=events_path,
        output_dir=tmp_path / "results", cache_dir=tmp_path / "cache",
        adapter=adapter, fail_fast_first=True,
    )
    assert adapter.calls == ["target-0"]
    assert result["complete"] is False
    assert result["unresolved_errors"] == 1
    assert result["events_scored"] == 0
