import json
from pathlib import Path

import pytest

import scripts.experiment as experiment_module
from scripts.base_eval import _structured_output
from scripts.experiment import Experiment, _json_fingerprint
from nanochat.experiment_metrics import (
    cumulative_pipeline_flops,
    rollout_generation_flops,
    training_flops,
)


def write_config(path, training=None, **overrides):
    config = {
        "schema_version": 1,
        "stage": "base",
        "experiment_id": "test-run",
        "dataset": {"adapter": "hf_stream", "repo": "owner/data"},
        "tokenizer": {"mode": "train"},
        "training": {"depth": 12, "total_batch_size": 100, **(training or {})},
        "artifacts": {"repo": "owner/models"},
    }
    config.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config))
    return path


def make_experiment(tmp_path, monkeypatch, path):
    monkeypatch.setenv("NANOCHAT_EXPERIMENT_ROOT", str(tmp_path / "runs"))
    return Experiment(path)


def test_explicit_token_horizon(tmp_path, monkeypatch):
    experiment = make_experiment(
        tmp_path,
        monkeypatch,
        write_config(tmp_path / "config.json", {"target_tokens": 1050}),
    )
    assert experiment._explicit_iterations() == 10


def test_epoch_horizon_uses_pretokenized_size(tmp_path, monkeypatch):
    experiment = make_experiment(
        tmp_path,
        monkeypatch,
        write_config(tmp_path / "config.json", {"epochs": 2.5}),
    )
    experiment.pretok_dir.mkdir(parents=True)
    (experiment.pretok_dir / "meta.json").write_text(
        json.dumps({"train_tokens": 1000})
    )
    assert experiment._explicit_iterations() == 25


def test_base_command_forwards_all_user_facing_flags(tmp_path, monkeypatch):
    training = {
        "device_type": "cuda",
        "depth": 12,
        "aspect_ratio": 64,
        "head_dim": 128,
        "max_seq_len": 2048,
        "target_param_data_ratio": 30.0,
        "window_pattern": "L",
        "device_batch_size": 16,
        "total_batch_size": 524288,
        "embedding_lr": 0.3,
        "unembedding_lr": 0.008,
        "weight_decay": 0.28,
        "matrix_lr": 0.02,
        "scalar_lr": 0.5,
        "warmup_steps": 40,
        "warmdown_ratio": 0.65,
        "final_lr_frac": 0.05,
        "eval_every": 250,
        "eval_tokens": 2097152,
        "core_metric_every": 500,
        "core_metric_max_per_task": 50,
        "sample_every": -1,
        "save_every": 500,
    }
    experiment = make_experiment(
        tmp_path,
        monkeypatch,
        write_config(tmp_path / "config.json", training),
    )
    command = experiment._base_train_command({"wandb_run_id": "run-id"})
    expected = {
        "--device-type=cuda",
        "--aspect-ratio=64",
        "--head-dim=128",
        "--max-seq-len=2048",
        "--embedding-lr=0.3",
        "--unembedding-lr=0.008",
        "--weight-decay=0.28",
        "--matrix-lr=0.02",
        "--scalar-lr=0.5",
        "--warmup-steps=40",
        "--warmdown-ratio=0.65",
        "--final-lr-frac=0.05",
        "--core-metric-max-per-task=50",
        "--target-param-data-ratio=30.0",
    }
    assert expected.issubset(set(command))
    assert not any(arg.startswith("--fp8") for arg in command)


def test_base_command_preserves_defaults_for_omitted_optional_flags(
    tmp_path, monkeypatch
):
    experiment = make_experiment(
        tmp_path,
        monkeypatch,
        write_config(
            tmp_path / "config.json",
            {"target_param_data_ratio": 12.0},
        ),
    )
    command = experiment._base_train_command({"wandb_run_id": "run-id"})
    optional_prefixes = (
        "--aspect-ratio=",
        "--head-dim=",
        "--max-seq-len=",
        "--embedding-lr=",
        "--warmdown-ratio=",
        "--core-metric-max-per-task=",
    )
    assert not any(arg.startswith(optional_prefixes) for arg in command)


def test_base_command_supports_target_flops(tmp_path, monkeypatch):
    experiment = make_experiment(
        tmp_path,
        monkeypatch,
        write_config(tmp_path / "config.json", {"target_flops": 1e18}),
    )
    command = experiment._base_train_command({"wandb_run_id": "run-id"})
    assert "--target-flops=1e+18" in command
    assert "--target-param-data-ratio=-1" in command


def test_fingerprint_is_order_independent():
    assert _json_fingerprint({"a": 1, "b": 2}) == _json_fingerprint(
        {"b": 2, "a": 1}
    )


def test_lineage_paths_allow_multiple_sft_children(tmp_path, monkeypatch):
    paths = []
    for sft_id in ("recipe-a", "recipe-b"):
        config = write_config(
            tmp_path / f"{sft_id}.json",
            {"num_iterations": 1},
            stage="sft",
            experiment_id=sft_id,
            parent={"base_experiment_id": "base-a", "checkpoint_step": 100},
        )
        experiment = make_experiment(tmp_path, monkeypatch, config)
        paths.append(experiment.root)
        assert experiment.hf_prefix == f"experiments/base-a/sft/{sft_id}"
    assert paths[0] != paths[1]


def test_posttrain_path_is_nested_under_exact_sft(tmp_path, monkeypatch):
    config = write_config(
        tmp_path / "post.json",
        {"num_epochs": 1},
        stage="posttrain",
        experiment_id="grpo-v1",
        parent={
            "base_experiment_id": "base-a",
            "sft_experiment_id": "recipe-a",
            "checkpoint_step": 200,
        },
    )
    experiment = make_experiment(tmp_path, monkeypatch, config)
    assert experiment.root == (
        tmp_path / "runs" / "base-a" / "sft" / "recipe-a"
        / "posttrain" / "grpo-v1"
    )
    assert experiment.hf_prefix.endswith(
        "base-a/sft/recipe-a/posttrain/grpo-v1"
    )


def test_invalid_downstream_parent_step_is_rejected(tmp_path, monkeypatch):
    config = write_config(
        tmp_path / "sft.json",
        {},
        stage="sft",
        experiment_id="recipe-a",
        parent={"base_experiment_id": "base-a"},
    )
    experiment = make_experiment(tmp_path, monkeypatch, config)
    with pytest.raises(ValueError, match="parent.checkpoint_step"):
        experiment.validate_config()


def test_local_config_is_immutable(tmp_path, monkeypatch):
    path = write_config(tmp_path / "config.json", {"target_tokens": 1000})
    experiment = make_experiment(tmp_path, monkeypatch, path)
    monkeypatch.setattr(experiment, "_validate_remote_config", lambda: None)
    experiment.initialize(recover_remote=True, upload_new=False)
    changed = json.loads(path.read_text())
    changed["training"]["target_tokens"] = 2000
    path.write_text(json.dumps(changed))
    changed_experiment = Experiment(path)
    with pytest.raises(RuntimeError, match="different local config"):
        changed_experiment.initialize(recover_remote=False, upload_new=False)


def test_complete_checkpoint_requires_optimizer(tmp_path, monkeypatch):
    experiment = make_experiment(
        tmp_path, monkeypatch, write_config(tmp_path / "config.json")
    )
    experiment.checkpoint_dir.mkdir(parents=True)
    (experiment.checkpoint_dir / "model_000100.pt").write_bytes(b"x")
    (experiment.checkpoint_dir / "meta_000100.json").write_text("{}")
    assert experiment.complete_local_steps() == []
    (experiment.checkpoint_dir / "optim_000100_rank0.pt").write_bytes(b"x")
    assert experiment.complete_local_steps() == [100]


def test_fresh_refuses_to_replace_remote_checkpoints(tmp_path, monkeypatch):
    experiment = make_experiment(
        tmp_path, monkeypatch, write_config(tmp_path / "config.json")
    )
    monkeypatch.setattr(
        experiment, "complete_remote_steps", lambda strict=False: [500, 1000]
    )
    with pytest.raises(RuntimeError, match="Refusing --fresh"):
        experiment.train(fresh=True)


def test_prepare_tokenizer_recovers_completed_local_files(tmp_path, monkeypatch):
    experiment = make_experiment(
        tmp_path, monkeypatch, write_config(tmp_path / "config.json")
    )
    experiment.tokenizer_dir.mkdir(parents=True)
    (experiment.tokenizer_dir / "tokenizer.pkl").write_bytes(b"tokenizer")
    (experiment.tokenizer_dir / "token_bytes.pt").write_bytes(b"token bytes")
    uploads = []
    monkeypatch.setattr(experiment, "download_folder", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        experiment, "upload_folder", lambda *args, **kwargs: uploads.append(args)
    )
    monkeypatch.setattr(
        experiment_module,
        "run_streaming",
        lambda *args, **kwargs: pytest.fail("tokenizer should not retrain"),
    )
    experiment.prepare_tokenizer()
    assert (experiment.tokenizer_dir / "experiment_tokenizer.json").exists()
    assert uploads


def test_pretokenized_no_wrap_rejects_exhausted_source(tmp_path, monkeypatch):
    config = write_config(
        tmp_path / "config.json",
        {
            "scaling_params": 1000,
            "target_param_data_ratio": 10.0,
            "total_batch_size": 100,
        },
        pretokenize={
            "enabled": True,
            "target_tokens": 11000,
            "require_no_wrap": True,
        },
    )
    experiment = make_experiment(tmp_path, monkeypatch, config)

    def fake_run(*args, **kwargs):
        experiment.pretok_dir.mkdir(parents=True, exist_ok=True)
        (experiment.pretok_dir / "meta.json").write_text(json.dumps({
            "train_tokens": 9000,
            "train_source_exhausted": True,
        }))

    monkeypatch.setattr(experiment_module, "run_streaming", fake_run)
    with pytest.raises(RuntimeError, match="source shards were exhausted"):
        experiment.prepare_pretokenized()


def test_stage_flops_are_cumulative(tmp_path, monkeypatch):
    config = write_config(
        tmp_path / "sft.json",
        {},
        stage="sft",
        experiment_id="recipe-a",
        parent={"base_experiment_id": "base-a", "checkpoint_step": 100},
    )
    experiment = make_experiment(tmp_path, monkeypatch, config)
    experiment.checkpoint_dir.mkdir(parents=True)
    experiment.eval_dir.mkdir(parents=True)
    (experiment.checkpoint_dir / "model_000010.pt").write_bytes(b"x")
    (experiment.checkpoint_dir / "optim_000010_rank0.pt").write_bytes(b"x")
    (experiment.checkpoint_dir / "meta_000010.json").write_text(json.dumps({
        "loop_state": {
            "stage_training_flops": 25.0,
            "inherited_parent_flops": 100.0,
            "cumulative_pipeline_training_flops": 125.0,
        }
    }))
    experiment.run_path.parent.mkdir(parents=True, exist_ok=True)
    experiment.run_path.write_text(json.dumps({"wandb_run_id": None}))
    monkeypatch.setattr(experiment, "initialize", lambda *args, **kwargs: None)
    monkeypatch.setattr(experiment, "remote_summary", lambda: {})
    experiment.tokenizer_dir.mkdir(parents=True)
    summary = experiment.build_summary()
    assert summary["stage_training_flops"] == 25.0
    assert summary["cumulative_pipeline_training_flops"] == 125.0


def test_base_summary_includes_structured_samples(tmp_path, monkeypatch):
    experiment = make_experiment(
        tmp_path,
        monkeypatch,
        write_config(
            tmp_path / "config.json",
            {"target_param_data_ratio": 12.0},
        ),
    )
    experiment.checkpoint_dir.mkdir(parents=True)
    experiment.eval_dir.mkdir(parents=True)
    (experiment.checkpoint_dir / "model_000010.pt").write_bytes(b"x")
    (experiment.checkpoint_dir / "optim_000010_rank0.pt").write_bytes(b"x")
    (experiment.checkpoint_dir / "meta_000010.json").write_text(json.dumps({
        "step": 10,
        "total_batch_size": 100,
        "val_bpb": 1.2,
        "loop_state": {
            "stage_training_flops": 25.0,
            "min_val_bpb": 1.1,
            "total_training_time": 5.0,
        },
    }))
    (experiment.eval_dir / "samples.json").write_text(json.dumps({
        "conditioned_samples": [{"prompt": "A", "text": "A B"}],
        "unconditioned_samples": ["Free text"],
    }))
    experiment.run_path.parent.mkdir(parents=True, exist_ok=True)
    experiment.run_path.write_text(json.dumps({"wandb_run_id": "run-id"}))
    monkeypatch.setattr(experiment, "initialize", lambda *args, **kwargs: None)
    monkeypatch.setattr(experiment, "remote_summary", lambda: {})
    experiment.tokenizer_dir.mkdir(parents=True)
    summary = experiment.build_summary()
    assert summary["conditioned_samples"] == [{"prompt": "A", "text": "A B"}]
    assert summary["unconditioned_samples"] == ["Free text"]


def test_structured_base_eval_output_includes_samples():
    output = _structured_output(
        "model",
        10,
        {"val": 1.0},
        {
            "core_metric": 0.2,
            "results": {"task": 0.5},
            "centered_results": {"task": 0.1},
        },
        [{"prompt": "A", "text": "A B"}],
        ["Free text"],
    )
    assert output["conditioned_samples"][0]["prompt"] == "A"
    assert output["unconditioned_samples"] == ["Free text"]


def test_ratio30_config_and_notebook_preflight():
    repo_root = Path(__file__).resolve().parents[1]
    config = json.loads(
        (repo_root / "configs/base/think-d12-1ep-65sh-r30.json").read_text()
    )
    training = config["training"]
    steps = int(
        training["target_param_data_ratio"] * training["scaling_params"]
    ) // training["total_batch_size"]
    training_tokens = steps * training["total_batch_size"]
    assert config["dataset"]["num_train_shards"] == 65
    assert steps == 6300
    assert training_tokens == 3303014400
    assert config["pretokenize"]["target_tokens"] == 3402104832
    assert config["pretokenize"]["require_no_wrap"] is True
    assert config["pretokenize"]["target_tokens"] > training_tokens

    notebook = json.loads(
        (repo_root / "dev/colab_nanochat_experiment.ipynb").read_text()
    )
    code = "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )
    compile(code.replace(
        '!python -u -m scripts.experiment prepare --config "$CONFIG_PATH"',
        "pass",
    ).replace(
        '!python -u -m scripts.experiment train --config "$CONFIG_PATH"',
        "pass",
    ).replace(
        '!python -u -m scripts.experiment eval --config "$CONFIG_PATH"',
        "pass",
    ).replace(
        "!python -u -m scripts.experiment wandb-workspace",
        "pass",
    ), "colab_nanochat_experiment.ipynb", "exec")
    assert "think-d12-1ep-65sh-r30.json" in code
    assert "No-wrap validation passed." in code
    assert "not independent ratio experiments" in code


def test_posttrain_flops_include_optimization_and_forward_only_rollouts():
    per_token = 900.0
    stage = training_flops(100, per_token)
    stage += rollout_generation_flops(60, per_token)
    assert stage == 108_000.0
    assert cumulative_pipeline_flops(stage, 1_000.0) == 109_000.0
