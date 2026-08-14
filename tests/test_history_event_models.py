from dev.history_event.models import MODEL_SPECS, model_allow_patterns


def test_immediate_bpb_model_set_contains_base_and_sft_gpt1900():
    assert set(MODEL_SPECS) == {
        "think-unbounded-d32-step9600",
        "gpt1900-d34",
        "gpt1900-sft",
        "llama-3.1-8b-instruct",
    }
    assert MODEL_SPECS["gpt1900-d34"]["cutoff_year"] == 1900
    assert MODEL_SPECS["gpt1900-sft"]["cutoff_year"] == 1900


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
