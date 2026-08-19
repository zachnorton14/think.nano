import json
from pathlib import Path

from nanochat.checkpoint_manager import checkpoint_architecture
from scripts.ifeval_common import merge_shards
from scripts.ifeval_official import GOOGLE_RESEARCH_REVISION
from scripts.run_ifeval_suite import completed_prefix, export_per_question_scores


ROOT = Path(__file__).resolve().parents[1]
MINI_INPUT_SOURCE = {
    "repo": "zakarth/ifeval-mini-120",
    "revision": "9cf942267717a4e5591540ce6e627446ff79d3f6",
    "filename": "data/test.jsonl",
    "sha256": "3a6bdab890e9800a91aa33891fc11a0cb3f1ecea7f5a14233030c2128e8d4e7c",
}


def test_four_model_mini_suite_is_complete_and_pinned_without_talkie():
    suite = json.loads(
        (ROOT / "configs/ifeval/four-models-mini120-v1.json").read_text()
    )
    assert suite["suite_id"] == "four-models-mini120-v1"
    assert suite["rows"] == 120
    assert suite["upload_every_questions"] == 100
    assert suite["official_ifeval_revision"] == GOOGLE_RESEARCH_REVISION
    assert suite["input_dataset"] == MINI_INPUT_SOURCE
    assert suite["generation"] == {
        "temperature": 0.0,
        "max_tokens": 1280,
        "system_prompt": None,
        "gpu_shards": 2,
    }
    assert [model["id"] for model in suite["models"]] == [
        "d32-c3rv3",
        "hla-gpt1900",
        "d32-modern-sft",
        "karpathy-d34-modern-sft",
    ]
    assert suite["artifacts"] == {
        "repo": "zachnorton03/synthetic-pre1930-sft",
        "repo_type": "dataset",
        "path": "evals/ifeval-four-models-mini120-v1",
    }


def test_master_pipeline_runs_two_gpu_worker_queue():
    launcher = (ROOT / "runs/train-two-then-ifeval-five-models.sh").read_text()
    assert "python -u -m scripts.run_train_eval_queue" in launcher
    assert "python -m ensurepip --upgrade" in launcher
    queue = (ROOT / "scripts/run_train_eval_queue.py").read_text()
    assert '"CUDA_VISIBLE_DEVICES": str(gpu_index)' in queue
    assert '"NPROC_PER_NODE": "1"' in queue
    assert 'eval_job("hla-gpt1900")' in queue
    assert 'eval_job("d32-modern-sft")' in queue
    assert '"train:c3rv3": "d32-c3rv3"' in queue
    assert '"train:d34-modern": "karpathy-d34-modern-sft"' in queue
    assert '"--gpu-shards",' in queue
    suite_runner = (ROOT / "scripts/run_ifeval_suite.py").read_text()
    assert 'state_lock = FileLock(str(output_root / ".suite-state.lock"))' in suite_runner
    assert 'if shard_count > 1 or "CUDA_VISIBLE_DEVICES" not in env:' in suite_runner
    assert 'parser.add_argument(\n        "--model-id"' in suite_runner

    for path in (
        "runs/Think.Unbounded-d32-v2mix-cont-pre1930-c3-robust-v3-sft.sh",
        "runs/karpathy-nanochat-d34-complete-modern-sft.sh",
    ):
        training_launcher = (ROOT / path).read_text()
        assert '--nproc-per-node "$NPROC_PER_NODE"' in training_launcher
        assert "SFT requires" in training_launcher


def test_karpathy_d34_sft_uses_complete_mixture_and_80gb_microbatch():
    config = json.loads(
        (
            ROOT
            / "configs/sft/karpathy-nanochat-d34-complete-modern-sft-v5-parallel-2xa100-80gb.json"
        ).read_text()
    )
    assert config["experiment_suffix"] == (
        "complete-modern-sft-v5-parallel-2xa100-80gb"
    )
    assert config["parent"] == {
        "base_experiment_id": "karpathy-nanochat-d34",
        "checkpoint_step": 169150,
    }
    assert config["data"]["recipe"] == "nanochat-default"
    assert config["data"]["max_train_presentations"] == -1
    assert config["training"]["load_optimizer"] == 0
    assert config["training"]["device_batch_size"] == 2
    assert config["training"]["total_batch_size"] == 524288
    launcher = (
        ROOT / "runs/karpathy-nanochat-d34-complete-modern-sft.sh"
    ).read_text()
    assert "identity_conversations.jsonl" in launcher
    assert "expected exactly 1,000" in launcher
    assert "--retry-all-errors" in launcher
    assert 'PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"' in launcher
    assert 'NANOCHAT_DIST_OPTIMIZER_LOW_MEMORY="${NANOCHAT_DIST_OPTIMIZER_LOW_MEMORY:-0}"' in launcher
    assert "80 GB-class GPU(s)" in launcher


def test_c3rv3_80gb_config_preserves_global_batch_with_micro_batch_two():
    config = json.loads(
        (
            ROOT
            / "configs/sft/pre1930-curriculum-c3-robust-v3-parallel-2xa100-80gb.json"
        ).read_text()
    )
    assert config["experiment_suffix"] == (
        "pre1930-curriculum-c3-robust-v3-parallel-2xa100-80gb"
    )
    assert config["training"]["device_batch_size"] == 2
    launcher = (
        ROOT / "runs/Think.Unbounded-d32-v2mix-cont-pre1930-c3-robust-v3-sft.sh"
    ).read_text()
    assert 'PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"' in launcher
    assert 'NANOCHAT_DIST_OPTIMIZER_LOW_MEMORY="${NANOCHAT_DIST_OPTIMIZER_LOW_MEMORY:-0}"' in launcher
    assert "80 GB-class GPU(s)" in launcher
    base = json.loads(
        (ROOT / "configs/base/Think.Unbounded-d32-v2mix-cont.json").read_text()
    )
    assert base["training"]["total_batch_size"] == 2097152


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


def test_merge_shards_requires_and_orders_all_120_rows(tmp_path):
    inputs = tmp_path / "input.jsonl"
    shard0 = tmp_path / "shard0.jsonl"
    shard1 = tmp_path / "shard1.jsonl"
    output = tmp_path / "responses.jsonl"
    model_id = "test-model"
    with inputs.open("w") as input_handle, shard0.open("w") as left, shard1.open(
        "w"
    ) as right:
        for key in range(120):
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
    assert len(rows) == 120
    assert [row["key"] for row in rows] == list(range(120))


def test_per_question_export_contains_long_and_wide_scores(tmp_path):
    inputs = tmp_path / "input.jsonl"
    inputs.write_text(
        json.dumps({
            "key": 10,
            "prompt": "Do both things",
            "instruction_id_list": ["first", "second"],
            "kwargs": [{}, {}],
        }) + "\n"
    )
    config = {
        "suite_id": "test-suite",
        "official_ifeval_revision": GOOGLE_RESEARCH_REVISION,
        "input_dataset": MINI_INPUT_SOURCE,
        "rows": 1,
        "generation": {"temperature": 0.0},
        "models": [
            {"id": "model-a", "backend": "nanochat-experiment"},
            {"id": "model-b", "backend": "nanochat-flat-hf"},
        ],
    }
    for model_index, model in enumerate(config["models"]):
        model_dir = tmp_path / model["id"]
        model_dir.mkdir()
        common = {
            "prompt": "Do both things",
            "response": f"answer {model_index}",
            "instruction_id_list": ["first", "second"],
        }
        strict = {
            **common,
            "follow_all_instructions": model_index == 0,
            "follow_instruction_list": [True, model_index == 0],
        }
        loose = {
            **common,
            "follow_all_instructions": True,
            "follow_instruction_list": [True, True],
        }
        (model_dir / "eval_results_strict.jsonl").write_text(
            json.dumps(strict) + "\n"
        )
        (model_dir / "eval_results_loose.jsonl").write_text(
            json.dumps(loose) + "\n"
        )

    manifest = export_per_question_scores(config, inputs, tmp_path)
    long_rows = read_jsonl_for_test(tmp_path / "per_question_long.jsonl")
    wide_rows = read_jsonl_for_test(tmp_path / "per_question_wide.jsonl")
    assert manifest["questions"] == 1
    assert manifest["long_rows"] == 2
    assert [row["model_id"] for row in long_rows] == ["model-a", "model-b"]
    assert long_rows[0]["strict_correct"] is True
    assert long_rows[1]["strict_correct"] is False
    assert long_rows[1]["strict_failed_instruction_ids"] == ["second"]
    assert long_rows[1]["loose_correct"] is True
    assert wide_rows[0]["question_key"] == 10
    assert wide_rows[0]["models"]["model-b"]["response"] == "answer 1"


def test_partial_export_skips_models_and_questions_not_scored_yet(tmp_path):
    inputs = tmp_path / "input.jsonl"
    inputs.write_text("".join(
        json.dumps({
            "key": key,
            "prompt": f"prompt {key}",
            "instruction_id_list": ["instruction"],
            "kwargs": [{}],
        }) + "\n"
        for key in range(2)
    ))
    config = {
        "suite_id": "partial-suite",
        "official_ifeval_revision": GOOGLE_RESEARCH_REVISION,
        "input_dataset": MINI_INPUT_SOURCE,
        "rows": 2,
        "generation": {"temperature": 0.0},
        "models": [
            {"id": "started", "backend": "nanochat-experiment"},
            {"id": "not-started", "backend": "nanochat-flat-hf"},
        ],
    }
    started = tmp_path / "started"
    started.mkdir()
    score = {
        "prompt": "prompt 0",
        "response": "answer",
        "instruction_id_list": ["instruction"],
        "follow_all_instructions": True,
        "follow_instruction_list": [True],
    }
    for label in ("strict", "loose"):
        (started / f"eval_results_{label}.jsonl").write_text(
            json.dumps(score) + "\n"
        )

    manifest = export_per_question_scores(
        config, inputs, tmp_path, allow_partial=True
    )
    rows = read_jsonl_for_test(tmp_path / "per_question_long.jsonl")
    assert len(rows) == 1
    assert rows[0]["question_key"] == 0
    assert manifest["per_model_rows"] == {"started": 1, "not-started": 0}
    assert manifest["questions_with_scores"] == 1
    assert manifest["complete"] is False


def test_completed_prefix_waits_for_contiguous_questions(tmp_path):
    inputs = tmp_path / "input.jsonl"
    shard0 = tmp_path / "shard0.jsonl"
    shard1 = tmp_path / "shard1.jsonl"
    model_id = "model"
    with inputs.open("w") as input_handle:
        for key in range(120):
            input_handle.write(json.dumps({
                "key": key,
                "prompt": f"prompt {key}",
            }) + "\n")
    shard0.write_text(json.dumps({
        "key": 0,
        "prompt": "prompt 0",
        "model_id": model_id,
    }) + "\n")
    shard1.write_text(json.dumps({
        "key": 2,
        "prompt": "prompt 2",
        "model_id": model_id,
    }) + "\n")
    assert [row["key"] for row in completed_prefix(
        inputs, [shard0, shard1], model_id
    )] == [0]


def read_jsonl_for_test(path):
    return [json.loads(line) for line in path.read_text().splitlines()]
