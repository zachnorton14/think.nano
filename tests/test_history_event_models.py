import types

import pytest
import torch

from dev.history_event.chart import MODEL_ORDER, MODEL_SETS
from dev.history_event.models import (
    MODEL_SPECS,
    _load_local_tiktoken_bpe,
    _talkie_full_logits,
    model_allow_patterns,
)


def test_registry_contains_full_seven_checkpoint_comparison():
    assert set(MODEL_SPECS) == {
        "think-unbounded-d32-step9600",
        "think-unbounded-d32-sft-c3-robust-v2",
        "gpt1900-d34",
        "gpt1900-sft",
        "talkie-1930-13b-base",
        "talkie-1930-13b-it",
        "llama-3.1-8b-instruct",
        "smollm3-3b",
    }
    assert MODEL_SPECS["gpt1900-d34"]["cutoff_year"] == 1900
    assert MODEL_SPECS["gpt1900-sft"]["cutoff_year"] == 1900


def test_full_bpb_order_pairs_base_and_instruction_checkpoints():
    assert MODEL_ORDER == [
        "think-unbounded-d32-step9600",
        "think-unbounded-d32-sft-c3-robust-v2",
        "gpt1900-d34",
        "gpt1900-sft",
        "talkie-1930-13b-base",
        "talkie-1930-13b-it",
        "llama-3.1-8b-instruct",
    ]
    assert MODEL_SETS["all-smollm3"] == [*MODEL_ORDER[:-1], "smollm3-3b"]


def test_smollm3_proxy_is_ungated_revision_pinned_without_invented_cutoff():
    spec = MODEL_SPECS["smollm3-3b"]
    assert spec["repo_id"] == "HuggingFaceTB/SmolLM3-3B"
    assert spec["revision"] == "a07cc9a04f16550a088caea529712d1d335b0ac1"
    assert spec["cutoff_year"] is None
    assert "No factual knowledge cutoff" in spec["cutoff_note"]


def test_gpt1900_sft_uses_its_own_artifacts_and_pinned_base_runtime():
    spec = MODEL_SPECS["gpt1900-sft"]
    assert spec["repo_id"] == "mhla/gpt1900-instruct-v3-sft"
    assert spec["revision"] == "346dddfe4aa82501fb17a5b4fd7d9bf678ebdca2"
    assert spec["checkpoint"] == "model_000075.pt"
    assert spec["metadata"] == "meta_000075.json"
    assert spec["runtime"] == {
        "kind": "huggingface",
        "repo_id": "mhla/gpt1900-d34-22btok",
        "revision": "d6330f9f0a17ce13da36fb951d7987bb03e6fbd0",
        "path": ".",
    }
    assert model_allow_patterns(spec) == [
        "model_000075.pt", "meta_000075.json", "tokenizer/**",
    ]


def test_think_sft_is_revision_and_training_runtime_pinned():
    spec = MODEL_SPECS["think-unbounded-d32-sft-c3-robust-v2"]
    assert spec["revision"] == "c5352cc09d914ae31c8301f6939970072accd014"
    assert spec["checkpoint"].endswith("checkpoints/model_000042.pt")
    assert spec["metadata"].endswith("checkpoints/meta_000042.json")
    assert spec["runtime"]["revision"] == "04bb043ad61d4db3e9022c422302df7b8f2dc0c9"


def test_talkie_variants_pin_models_runtime_and_minimal_downloads():
    base = MODEL_SPECS["talkie-1930-13b-base"]
    tuned = MODEL_SPECS["talkie-1930-13b-it"]
    assert base["revision"] == "b7c97680791f7fca4262c3c80b36ff7d666faab0"
    assert tuned["revision"] == "8033675be6360ae0127fa75f941c12d52064f1dc"
    assert base["runtime"]["revision"] == tuned["runtime"]["revision"]
    assert base["runtime"]["revision"] == "35317ba3a84861a84c84065bd73faf88ad19329c"
    assert model_allow_patterns(base) == ["final.ckpt", "vocab.txt"]
    assert model_allow_patterns(tuned) == ["rl-refined.pt", "vocab.txt"]


def test_talkie_full_logits_scores_every_position():
    class PassBlock(torch.nn.Module):
        def forward(self, embedded, hidden, cos_sin):
            return hidden

    model = types.SimpleNamespace(
        embed=torch.nn.Embedding(7, 4),
        blocks=[PassBlock()],
        cos=torch.zeros(1, 4, 1, 2),
        sin=torch.zeros(1, 4, 1, 2),
        lm_head=torch.nn.Parameter(torch.randn(7, 4)),
        lm_head_gain=torch.nn.Identity(),
    )
    token_ids = torch.tensor([[1, 2, 3]])
    logits = _talkie_full_logits(model, token_ids)
    assert logits.shape == (1, 3, 7)
    hidden = torch.nn.functional.rms_norm(model.embed(token_ids), (4,))
    expected = torch.nn.functional.linear(
        torch.nn.functional.rms_norm(hidden, (4,)), model.lm_head
    ).float()
    assert torch.allclose(logits, expected)


def test_local_talkie_vocab_parser_needs_no_blobfile(tmp_path):
    vocab = tmp_path / "vocab.txt"
    vocab.write_bytes(b"QQ== 0\nw6k= 1\n")
    assert _load_local_tiktoken_bpe(vocab) == {b"A": 0, "é".encode(): 1}
    vocab.write_bytes(b"malformed\n")
    with pytest.raises(ValueError, match="line 1"):
        _load_local_tiktoken_bpe(vocab)
