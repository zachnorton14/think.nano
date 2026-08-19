import json
from pathlib import Path

from nanochat.checkpoint_manager import checkpoint_architecture
from scripts.ifeval_common import merge_shards
from scripts.ifeval_official import GOOGLE_RESEARCH_REVISION


ROOT = Path(__file__).resolve().parents[1]


def test_five_model_suite_is_complete_and_pinned():
    suite = json.loads((ROOT / "configs/ifeval/five-models-v1.json").read_text())
    assert suite["rows"] == 541
    assert suite["official_ifeval_revision"] == GOOGLE_RESEARCH_REVISION
    assert suite["generation"] == {
        "temperature": 0.0,
        "max_tokens": 1280,
        "system_prompt": None,
        "gpu_shards": 2,
    }
    assert [model["id"] for model in suite["models"]] == [
        "d32-c3rv3",
        "hla-gpt1900",
        "talkie-1930-13b-it",
        "d32-modern-sft",
        "karpathy-d34-modern-sft",
    ]
    talkie = suite["models"][2]
    assert talkie["repo_url"] == "https://github.com/talkie-lm/talkie.git"
    assert len(talkie["revision"]) == 40


def test_karpathy_d34_sft_uses_complete_mixture_and_fresh_optimizer():
    config = json.loads(
        (ROOT / "configs/sft/karpathy-nanochat-d34-complete-modern-sft-v1.json")
        .read_text()
    )
    assert config["parent"] == {
        "base_experiment_id": "karpathy-nanochat-d34",
        "checkpoint_step": 169150,
    }
    assert config["data"]["recipe"] == "nanochat-default"
    assert config["data"]["max_train_presentations"] == -1
    assert config["training"]["load_optimizer"] == 0


def test_checkpoint_architecture_detection_uses_state_keys():
    assert checkpoint_architecture({"transformer.wte.weight": object()}) == (
        "nanochat_legacy_2025"
    )
    assert checkpoint_architecture({"value_embeds.1.weight": object()}) == (
        "nanochat_resformer_2026"
    )
    assert checkpoint_architecture({"smear_lambda": object()}) == "nanochat_current"
    assert checkpoint_architecture(
        {"smear_lambda": object()},
        {"model_architecture": "nanochat_legacy_2025"},
    ) == "nanochat_legacy_2025"


def test_merge_shards_requires_and_orders_all_541_rows(tmp_path):
    inputs = tmp_path / "input.jsonl"
    shard0 = tmp_path / "shard0.jsonl"
    shard1 = tmp_path / "shard1.jsonl"
    output = tmp_path / "responses.jsonl"
    model_id = "test-model"
    with inputs.open("w") as input_handle, shard0.open("w") as left, shard1.open(
        "w"
    ) as right:
        for key in range(541):
            prompt = f"prompt {key}"
            input_handle.write(json.dumps({"key": key, "prompt": prompt}) + "\n")
            result = {
                "key": key,
                "prompt": prompt,
                "response": f"response {key}",
                "model_id": model_id,
            }
            (left if key % 2 == 0 else right).write(json.dumps(result) + "\n")
    merge_shards(inputs, [shard0, shard1], output, model_id)
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 541
    assert [row["key"] for row in rows] == list(range(541))
