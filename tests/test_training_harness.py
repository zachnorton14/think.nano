import json

import pytest

import scripts.experiment as experiment_module
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


def test_posttrain_flops_include_optimization_and_forward_only_rollouts():
    per_token = 900.0
    stage = training_flops(100, per_token)
    stage += rollout_generation_flops(60, per_token)
    assert stage == 108_000.0
    assert cumulative_pipeline_flops(stage, 1_000.0) == 109_000.0
