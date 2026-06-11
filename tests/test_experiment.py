import json

import pytest

from scripts.experiment import Experiment, _json_fingerprint, collect_summaries


def write_config(path, training):
    config = {
        "experiment_id": "test-run",
        "dataset": {"adapter": "hf_stream", "repo": "owner/data"},
        "training": {"depth": 12, "total_batch_size": 100, **training},
    }
    path.write_text(json.dumps(config))
    return path


def test_explicit_token_horizon(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOCHAT_EXPERIMENT_ROOT", str(tmp_path / "runs"))
    experiment = Experiment(write_config(tmp_path / "config.json", {"target_tokens": 1050}))
    assert experiment._explicit_iterations() == 10


def test_epoch_horizon_uses_pretokenized_size(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOCHAT_EXPERIMENT_ROOT", str(tmp_path / "runs"))
    experiment = Experiment(write_config(tmp_path / "config.json", {"epochs": 2.5}))
    experiment.pretok_dir.mkdir(parents=True)
    (experiment.pretok_dir / "meta.json").write_text(json.dumps({"train_tokens": 1000}))
    assert experiment._explicit_iterations() == 25


def test_fingerprint_is_order_independent():
    assert _json_fingerprint({"a": 1, "b": 2}) == _json_fingerprint({"b": 2, "a": 1})


def test_collect_summaries_includes_local_results(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "experiments").mkdir()
    (tmp_path / "experiments" / "historical_runs.json").write_text("[]")
    run_dir = tmp_path / "runs" / "test"
    run_dir.mkdir(parents=True)
    (run_dir / "summary.json").write_text(json.dumps({"experiment_id": "test"}))
    assert collect_summaries(tmp_path / "runs") == [{"experiment_id": "test"}]


def test_fresh_refuses_to_replace_remote_checkpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOCHAT_EXPERIMENT_ROOT", str(tmp_path / "runs"))
    experiment = Experiment(write_config(tmp_path / "config.json", {}))
    monkeypatch.setattr(
        experiment, "complete_remote_steps", lambda strict=False: [500, 1000, 1500]
    )
    with pytest.raises(RuntimeError, match="Refusing --fresh"):
        experiment.train(fresh=True)
