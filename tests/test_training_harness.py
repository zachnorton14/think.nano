import json
import re
import sys
import types
from pathlib import Path

import pytest

import scripts.experiment as experiment_module
from scripts.base_eval import _structured_output
from scripts.experiment import Experiment, _copy_cached_file, _json_fingerprint
from scripts.pretok_think import _tokenizer_fingerprint
from nanochat.experiment_metrics import (
    checkpoint_compute_fields,
    compute_log_fields,
    configure_wandb_metrics,
    cumulative_pipeline_flops,
    fixed_batch_stage_flops,
    rollout_generation_flops,
    training_flops,
    update_wandb_compute_summary,
    update_wandb_lineage_summary,
)
from scripts.gpu_preflight import _cuda_version_tuple, _validate_full_nvlink_topology
from scripts.container_smoke import _validate_prebuilt_lock


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


def test_cached_artifact_copy_avoids_shutil_fast_copy(tmp_path, monkeypatch):
    source = tmp_path / "cached.bin"
    destination = tmp_path / "experiment" / "artifact.bin"
    source.write_bytes(b"hosted artifact")

    def fail_fast_copy(*args, **kwargs):
        raise OSError(28, "spurious overlayfs ENOSPC")

    monkeypatch.setattr(experiment_module.shutil, "copy2", fail_fast_copy)
    _copy_cached_file(source, destination)

    assert destination.read_bytes() == b"hosted artifact"
    assert not destination.with_name("artifact.bin.copying").exists()


def test_cached_artifact_copy_preserves_destination_on_interruption(
    tmp_path, monkeypatch
):
    source = tmp_path / "cached.bin"
    destination = tmp_path / "artifact.bin"
    source.write_bytes(b"replacement")
    destination.write_bytes(b"existing")

    def interrupt_copy(source_file, destination_file, length):
        destination_file.write(b"partial")
        raise OSError("interrupted")

    monkeypatch.setattr(experiment_module.shutil, "copyfileobj", interrupt_copy)
    with pytest.raises(OSError, match="interrupted"):
        _copy_cached_file(source, destination)

    assert destination.read_bytes() == b"existing"
    assert not destination.with_name("artifact.bin.copying").exists()


def test_missing_remote_experiment_path_is_empty(tmp_path, monkeypatch):
    from huggingface_hub.errors import EntryNotFoundError

    experiment = make_experiment(
        tmp_path, monkeypatch, write_config(tmp_path / "config.json")
    )

    class MissingPathApi:
        def list_repo_tree(self, *args, **kwargs):
            raise EntryNotFoundError("missing experiment path")

    experiment._api = MissingPathApi()
    assert experiment.remote_files(strict=True) == set()


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
        "muon_momentum": 0.9,
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
        "--muon-momentum=0.9",
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
        "--muon-momentum=",
        "--warmdown-ratio=",
        "--core-metric-max-per-task=",
    )
    assert not any(arg.startswith(optional_prefixes) for arg in command)


@pytest.mark.parametrize("value", [-0.01, 1.0, True, "0.9"])
def test_base_config_rejects_invalid_constant_muon_momentum(
    tmp_path, monkeypatch, value
):
    experiment = make_experiment(
        tmp_path,
        monkeypatch,
        write_config(tmp_path / "config.json", {"muon_momentum": value}),
    )
    with pytest.raises(ValueError, match="muon_momentum"):
        experiment.validate_config()


def test_base_command_supports_target_flops(tmp_path, monkeypatch):
    experiment = make_experiment(
        tmp_path,
        monkeypatch,
        write_config(tmp_path / "config.json", {"target_flops": 1e18}),
    )
    command = experiment._base_train_command({"wandb_run_id": "run-id"})
    assert "--target-flops=1e+18" in command
    assert "--target-param-data-ratio=-1" in command


def test_single_process_command_is_unchanged_by_explicit_default(tmp_path, monkeypatch):
    path = write_config(
        tmp_path / "config.json",
        {"target_param_data_ratio": 12.0},
    )
    implicit = make_experiment(tmp_path, monkeypatch, path)
    explicit = Experiment(path, nproc_per_node=1)
    assert implicit._base_train_command({"wandb_run_id": "run-id"}) == (
        explicit._base_train_command({"wandb_run_id": "run-id"})
    )


@pytest.mark.parametrize("nproc_per_node", [4, 8])
def test_base_command_wraps_torchrun_and_forwards_fp8(
    tmp_path, monkeypatch, nproc_per_node
):
    experiment = make_experiment(
        tmp_path,
        monkeypatch,
        write_config(
            tmp_path / "config.json",
            {
                "target_param_data_ratio": 12.0,
                "fp8": True,
                "fp8_recipe": "tensorwise",
            },
        ),
    )
    experiment.nproc_per_node = nproc_per_node
    command = experiment._base_train_command({"wandb_run_id": "run-id"})
    assert command[:9] == [
        sys.executable,
        "-u",
        "-m",
        "torch.distributed.run",
        "--standalone",
        f"--nproc-per-node={nproc_per_node}",
        "-m",
        "scripts.base_train",
        "--",
    ]
    assert "--fp8" in command
    assert "--fp8-recipe=tensorwise" in command
    assert "--target-param-data-ratio=12.0" in command


def test_d24_sssl_config_matches_hosted_spec_and_ratio_horizon(
    tmp_path, monkeypatch
):
    config_path = (
        Path(__file__).resolve().parents[1]
        / "configs/base/clean1930s-d24-r12-ctx4096-sssl-fulltok-v1.json"
    )
    config = json.loads(config_path.read_text())
    assert _json_fingerprint(config) == "166e7e695c1b536a"
    assert "target_tokens" not in config["training"]
    assert config["dataset"]["num_train_shards"] == 180
    assert config["tokenizer"] == {
        "mode": "reuse",
        "source_experiment_id": "clean1930s-d24-r12-ctx4096-fulltok-v1",
        "vocab_size": 32768,
    }
    assert config["artifacts"]["keep_local_checkpoints"] == 1

    training = config["training"]
    assert training["window_pattern"] == "SSSL"
    raw_target = training["target_param_data_ratio"] * training["scaling_params"]
    steps = raw_target // training["total_batch_size"]
    realized_tokens = steps * training["total_batch_size"]
    assert steps == 8352
    assert realized_tokens == 8_757_706_752
    assert int(realized_tokens * config["pretokenize"]["slack"] + 0.999999) == (
        9_020_437_955
    )
    full_attention_flops_per_token = 6_190_803_072
    long_attention = 12 * 12 * 128 * 4096
    short_attention = 12 * 12 * 128 * 1024
    matrix_flops = full_attention_flops_per_token - 24 * long_attention
    sssl_flops_per_token = matrix_flops + 6 * long_attention + 18 * short_attention
    assert sssl_flops_per_token == 5_171_587_200
    assert sssl_flops_per_token * realized_tokens == 45_291_244_139_996_774_400

    monkeypatch.setenv("NANOCHAT_EXPERIMENT_ROOT", str(tmp_path / "runs"))
    experiment = Experiment(config_path, nproc_per_node=4)
    command = experiment._base_train_command({"wandb_run_id": "run-id"})
    assert "--max-seq-len=4096" in command
    assert "--window-pattern=SSSL" in command
    assert "--device-batch-size=8" in command
    assert "--total-batch-size=1048576" in command
    assert "--target-param-data-ratio=12" in command
    assert not any(arg.startswith("--num-iterations=") for arg in command)


def test_d24_vast_script_defaults_to_eight_gpu_preflight():
    script = (
        Path(__file__).resolve().parents[1]
        / "runs/clean1930s-d24-r12.sh"
    ).read_text()
    assert 'NPROC_PER_NODE="${NPROC_PER_NODE:-8}"' in script
    assert 'ALLOW_SINGLE_GPU="${ALLOW_SINGLE_GPU:-0}"' in script
    assert 'REQUIRE_FULL_NVLINK="${REQUIRE_FULL_NVLINK:-1}"' in script
    assert "clean1930s-d24-r12-ctx4096-sssl-fulltok-v1.json" in script
    assert "DEFAULT_NANOCHAT_BASE_DIR=/workspace/nanochat" in script
    assert 'TORCHINDUCTOR_COMPILE_THREADS="${TORCHINDUCTOR_COMPILE_THREADS:-1}"' in script
    assert "NANOCHAT_PREBUILT_VENV" in script
    assert "cmp -s uv.lock" in script
    assert "uv sync --frozen --extra gpu" in script
    assert "-m scripts.gpu_preflight" in script
    assert '--expected-gpus "$NPROC_PER_NODE"' in script
    assert "--require-full-nvlink" in script
    assert script.index("-m scripts.gpu_preflight") < script.index(
        "snapshot_download("
    )


def test_d12_attention_ablation_configs_are_matched(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    paths = {
        "SSSL": root / "configs/base/clean1930s-d12-r11.25-ctx4096-sssl-fulltok-ablation-v1.json",
        "L": root / "configs/base/clean1930s-d12-r11.25-ctx4096-full-fulltok-ablation-v1.json",
    }
    configs = {pattern: json.loads(path.read_text()) for pattern, path in paths.items()}

    def comparison_payload(config):
        payload = json.loads(json.dumps(config))
        payload.pop("experiment_id")
        payload["training"].pop("window_pattern")
        payload["wandb"].pop("name")
        payload["wandb"]["tags"] = sorted(
            tag for tag in payload["wandb"]["tags"]
            if tag not in {"sssl", "full-attention"}
        )
        return payload

    assert comparison_payload(configs["SSSL"]) == comparison_payload(configs["L"])
    for pattern, config in configs.items():
        assert config["training"]["window_pattern"] == pattern
        assert config["training"]["max_seq_len"] == 4096
        assert config["training"]["fp8"] is True
        assert config["training"]["fp8_recipe"] == "tensorwise"
        assert config["tokenizer"]["source_experiment_id"] == (
            "clean1930s-d24-r12-ctx4096-fulltok-v1"
        )
        assert config["dataset"]["num_train_shards"] == 180
        assert config["pretokenize"]["require_no_wrap"] is True

        training = config["training"]
        steps = int(
            training["target_param_data_ratio"]
            * training["scaling_params"]
            // training["total_batch_size"]
        )
        assert steps == 2362
        assert steps * training["total_batch_size"] == 1_238_368_256

        monkeypatch.setenv("NANOCHAT_EXPERIMENT_ROOT", str(tmp_path / pattern))
        command = Experiment(paths[pattern], nproc_per_node=1)._base_train_command(
            {"wandb_run_id": "run-id"}
        )
        assert "torch.distributed.run" not in command
        assert f"--window-pattern={pattern}" in command
        assert "--max-seq-len=4096" in command
        assert "--fp8" in command
        assert "--fp8-recipe=tensorwise" in command
        assert "--target-param-data-ratio=11.25" in command
        assert not any(arg.startswith("--num-iterations=") for arg in command)


def test_d24_mixture_config_scales_run2_schedule_to_the_d24_horizon():
    """clean1930s-d24-r12-ctx4096-sssl-fulltok-mix-og is the d24 SSSL config with
    1930s-d12-r12-4096ctx-run2's 70/20/10 mixture scaled to the d24 token horizon."""
    root = Path(__file__).resolve().parents[1]
    single = json.loads(
        (root / "configs/base/clean1930s-d24-r12-ctx4096-sssl-fulltok-v1.json").read_text()
    )
    run2 = json.loads(
        (root / "configs/base/1930s-d12-r12-4096ctx-run2.json").read_text()
    )
    config = json.loads(
        (root / "configs/base/clean1930s-d24-r12-ctx4096-sssl-fulltok-mix-og.json").read_text()
    )

    # Same model, tokenizer, and pretokenization as the d24 single-source run; only
    # the data becomes a mixture.
    for key in ("training", "tokenizer", "pretokenize", "artifacts"):
        assert config[key] == single[key], key
    assert "dataset" not in config
    assert set(config["datasets"]) == set(run2["datasets"])

    training = config["training"]
    batch = training["total_batch_size"]
    steps = int(training["target_param_data_ratio"] * training["scaling_params"]) // batch
    assert steps == 8352
    schedule = config["mixture_schedule"]
    assert schedule["total_tokens"] == steps * batch == 8_757_706_752
    assert schedule["seed_data"] == run2["mixture_schedule"]["seed_data"]
    assert schedule["max_epochs"] == run2["mixture_schedule"]["max_epochs"]

    # Same stage names and sources, in the same order, at the same proportions.
    stages = config["mixture_schedule"]["stages"]
    run2_stages = run2["mixture_schedule"]["stages"]
    assert [(s["name"], s["source"]) for s in stages] == [
        (s["name"], s["source"]) for s in run2_stages
    ]
    for stage in stages:
        assert stage["start_tokens"] % batch == 0, stage["name"]

    def proportions(schedule_stages, total):
        bounds = [s["start_tokens"] for s in schedule_stages] + [total]
        return [(bounds[i + 1] - bounds[i]) / total for i in range(len(schedule_stages))]

    scaled = proportions(stages, schedule["total_tokens"])
    reference = proportions(run2_stages, run2["mixture_schedule"]["total_tokens"])
    assert reference == [0.7, 0.2, 0.1]
    for got, want in zip(scaled, reference):
        assert abs(got - want) < 1e-3, (scaled, reference)


def test_d24_mixture_config_has_enough_shards_per_source():
    """Each source must supply its planned draw plus pretokenize slack, or preparation
    dies after a multi-hour download. Tokens per shard are measured from the hosted
    parquet: a 1930s shard carries ~219 MB of text, a midtrain shard ~50 MB, and this
    tokenizer averages <= 4.38 bytes per token."""
    root = Path(__file__).resolve().parents[1]
    config = json.loads(
        (root / "configs/base/clean1930s-d24-r12-ctx4096-sssl-fulltok-mix-og.json").read_text()
    )
    batch = config["training"]["total_batch_size"]
    slack = config["pretokenize"]["slack"]
    schedule = config["mixture_schedule"]
    bounds = [s["start_tokens"] for s in schedule["stages"]] + [schedule["total_tokens"]]
    draw = {
        stage["source"]: bounds[index + 1] - bounds[index]
        for index, stage in enumerate(schedule["stages"])
    }
    # Conservative tokens per train shard, and shards published in each repo.
    tokens_per_shard = {"original": 49_000_000, "midtrain_r30": 11_900_000, "midtrain_r60": 11_700_000}
    published = {"original": 473, "midtrain_r30": 1263, "midtrain_r60": 525}

    for source, dataset in config["datasets"].items():
        shards = dataset["num_train_shards"]
        needed = draw[source] * slack
        assert shards * tokens_per_shard[source] >= needed, source
        assert shards <= published[source], source
        # nanochat.dataset clamps -n to --max-shard and the pretokenizer takes the
        # last-sorted parquet as validation, so the val index must clear the train range.
        assert dataset["validation_shard"] >= shards, source
        assert dataset["validation_shard"] < published[source], source
    # The headline val BPB reads the first source, so it stays the 1930s val shard
    # every other clean1930s run reports on.
    assert config["datasets"]["original"]["validation_shard"] == 472
    assert schedule["stages"][0]["source"] == "original"


def test_think_unbounded_d32_config_has_the_final_mixture_horizon_and_capacity():
    """The final d32 run is a fresh r12 pretrain with the established 70/20/10
    original/r30/r60 curriculum, not a continuation from the d24 checkpoint."""
    root = Path(__file__).resolve().parents[1]
    path = root / "configs/base/Think.Unbounded-d32.json"
    config = json.loads(path.read_text())

    assert not (root / "configs/base/ThinkUnbounded-d32.json").exists()
    assert config["experiment_id"] == "Think.Unbounded-d32"
    assert config["wandb"]["name"] == "Think.Unbounded-d32"
    assert "branch" not in config
    assert config["datasets"]["original"]["revision"] == (
        "45225d95bc15f942be3b4b344738cea1f66e3de8"
    )
    assert {
        config["datasets"][source]["revision"]
        for source in ("midtrain_r30", "midtrain_r60")
    } == {"9ace24b8e16e57e38a1ea0b1f6d7cbf323bf9dbc"}

    training = config["training"]
    batch = training["total_batch_size"]
    schedule = config["mixture_schedule"]
    assert schedule["total_tokens"] == 20_132_659_200
    assert schedule["total_tokens"] == 9_600 * batch
    assert schedule["total_tokens"] <= 12 * training["scaling_params"]
    assert 12 * training["scaling_params"] - schedule["total_tokens"] < batch

    stages = schedule["stages"]
    bounds = [stage["start_tokens"] for stage in stages] + [schedule["total_tokens"]]
    draws = {
        stage["source"]: bounds[index + 1] - bounds[index]
        for index, stage in enumerate(stages)
    }
    assert [stage["start_tokens"] // batch for stage in stages] == [0, 6_720, 8_640]
    assert [draws[stage["source"]] / schedule["total_tokens"] for stage in stages] == [
        0.7,
        0.2,
        0.1,
    ]

    # Conservative measured token yields. Catch an undersized shard plan before a
    # multi-hour download and tokenize pass reaches the end of a source.
    tokens_per_shard = {
        "original": 49_000_000,
        "midtrain_r30": 11_900_000,
        "midtrain_r60": 11_700_000,
    }
    slack = config["pretokenize"]["slack"]
    for source, dataset in config["datasets"].items():
        assert dataset["num_train_shards"] * tokens_per_shard[source] >= draws[source] * slack
        assert dataset["validation_shard"] >= dataset["num_train_shards"]

    assert config["pretokenize"]["require_no_wrap"] is True
    assert training["max_seq_len"] == 4096
    assert training["window_pattern"] == "SSSL"
    assert training["muon_momentum"] == 0.9
    assert training["device_batch_size"] == 2
    assert training["eval_tokens"] == 2_097_152
    assert training["core_metric_every"] == -1
    assert {"muon-momentum-constant", "muon-momentum-0.90"} <= set(
        config["wandb"]["tags"]
    )

    experiment = Experiment(path, nproc_per_node=1)
    command = experiment._base_train_command({"wandb_run_id": "run-id"})
    assert "--muon-momentum=0.9" in command
    assert "--device-batch-size=2" in command


def test_think_unbounded_d32_runner_gates_the_production_run():
    root = Path(__file__).resolve().parents[1]
    script = (root / "runs/Think.Unbounded-d32.sh").read_text()

    assert "preflight|prepare|smoke|train|eval|plan" in script
    assert "Think.Unbounded-d32.json" in script
    assert "verify_caches" in script
    assert "verify_smoke_marker" in script
    assert "--expected-gpus 1" in script
    assert "--depth=32" in script
    assert "--max-seq-len=4096" in script
    assert "--window-pattern=SSSL" in script
    assert "--device-batch-size=2" in script
    assert "--muon-momentum=0.9" in script
    assert "--fp8-recipe=tensorwise" in script
    assert "scripts.experiment prepare" in script
    assert "scripts.experiment train" in script
    assert "--per-position-bpb-only" in script
    assert "--core-only" not in script
    assert "|all)" not in script


def test_think_unbounded_d32_v2mix_continuation_is_a_step_5500_data_repair():
    root = Path(__file__).resolve().parents[1]
    parent = json.loads(
        (root / "configs/base/Think.Unbounded-d32.json").read_text()
    )
    path = root / "configs/base/Think.Unbounded-d32-v2mix-cont.json"
    child = json.loads(path.read_text())

    assert child["experiment_id"] == "Think.Unbounded-d32-v2mix-cont"
    assert child["branch"] == {
        "parent_experiment_id": "Think.Unbounded-d32",
        "parent_step": 5500,
        "lr_schedule": "continue",
        "load_optimizer": True,
    }
    assert child["branch"]["parent_step"] % parent["training"]["save_every"] == 0

    # Architecture, optimizer settings, horizon, tokenizer, and the original corpus
    # remain the parent's. This is a future-data repair, not a new training recipe.
    for key in ("training", "tokenizer", "artifacts"):
        assert child[key] == parent[key], key
    assert child["mixture_schedule"]["total_tokens"] == parent["mixture_schedule"]["total_tokens"]
    assert [s["start_tokens"] for s in child["mixture_schedule"]["stages"]] == [
        s["start_tokens"] for s in parent["mixture_schedule"]["stages"]
    ]
    assert child["datasets"]["original"] == parent["datasets"]["original"]

    revision = "5250c497c8c72558a573dbcd216e26ea3c76e6e2"
    assert child["datasets"]["midtrain_r21"] == {
        "adapter": "parquet_shards",
        "repo": "zachnorton03/think-midtrain",
        "revision": revision,
        "subfolder": "mixed/v2/ratio_21/data",
        "validation_shard": 65,
        "num_train_shards": 65,
        "download_workers": 4,
    }
    assert child["datasets"]["midtrain_r45"] == {
        "adapter": "parquet_shards",
        "repo": "zachnorton03/think-midtrain",
        "revision": revision,
        "subfolder": "mixed/v2/ratio_45/data",
        "validation_shard": 33,
        "num_train_shards": 33,
        "download_workers": 4,
    }
    assert [s["source"] for s in child["mixture_schedule"]["stages"]] == [
        "original", "midtrain_r21", "midtrain_r45",
    ]
    assert child["pretokenize"] == {**parent["pretokenize"], "slack": 1.02}

    experiment = Experiment(path, nproc_per_node=1)
    experiment.validate_config()
    assert experiment.mixture_start_tokens == 5500 * child["training"]["total_batch_size"]
    assert experiment.active_mixture_sources == [
        "original", "midtrain_r21", "midtrain_r45",
    ]
    command = experiment._base_train_command({"wandb_run_id": "run-id"})
    assert "--init-from-step=5500" in command
    assert "--branch-lr-schedule=continue" in command
    assert "--num-iterations=9600" in command


def test_think_unbounded_d32_v2mix_runner_preserves_the_parent_data_cursor():
    root = Path(__file__).resolve().parents[1]
    script = (root / "runs/Think.Unbounded-d32-v2mix-cont.sh").read_text()

    assert "prepare-data|prepare-parent|train" in script
    assert "Think.Unbounded-d32-v2mix-cont.json" in script
    assert 'PARENT_ROOT="$NANOCHAT_EXPERIMENT_ROOT/Think.Unbounded-d32"' in script
    assert 'ln -s "$parent_original" "$child_original"' in script
    assert "the restored cursor requires the exact parent cache" in script
    assert "prepare_data_without_parent_checkpoint" in script
    assert "experiment.prepare_dataset()" in script
    assert "experiment.prepare_pretokenized()" in script
    assert "Do not call" in script and "prepare_tokenizer()" in script
    assert "verify_dataset_manifests" in script
    assert "verify_caches" in script
    assert "verify_parent_smoke" in script
    assert "scripts.experiment train" in script


def test_think_unbounded_d32_final_eval_covers_full_bpb_and_all_vintage_bundles():
    root = Path(__file__).resolve().parents[1]
    script = (
        root / "runs/Think.Unbounded-d32-v2mix-cont-full-eval.sh"
    ).read_text()
    base_eval = (root / "scripts/base_eval.py").read_text()

    assert "Think.Unbounded-d32-v2mix-cont.sh eval" in script
    assert 'STEP=9600' in script
    assert 'revision="v1.0.0"' in script
    assert "run_core original" in script
    assert "run_core filtered" in script
    assert "run_core restyled" in script
    assert "--max-per-task=-1" in script
    assert "eval/vintage_core" in script
    assert "scripts.experiment sync" in script
    assert "--core-bundle-dir" in base_eval


def test_d12_ablation_wrapper_has_one_command_per_attention_mode():
    root = Path(__file__).resolve().parents[1]
    script = (
        root / "runs/clean1930s-d12-r11.25-ctx4096-ablation.sh"
    ).read_text()
    assert "sssl)" in script
    assert "full)" in script
    assert "ctx4096-sssl-fulltok-ablation-v1.json" in script
    assert "ctx4096-full-fulltok-ablation-v1.json" in script
    assert 'NPROC_PER_NODE="${NPROC_PER_NODE:-1}"' in script
    assert "ALLOW_SINGLE_GPU=1" in script
    assert 'REQUIRE_FULL_NVLINK="${REQUIRE_FULL_NVLINK:-0}"' in script
    assert 'MIN_FREE_GIB="${MIN_FREE_GIB:-80}"' in script
    assert 'exec bash "$SCRIPT_DIR/clean1930s-d24-r12.sh"' in script


def test_vast_launcher_shares_hosted_pretokenized_cache():
    script = (
        Path(__file__).resolve().parents[1] / "runs/clean1930s-d24-r12.sh"
    ).read_text()
    assert "HOSTED_PRETOKENIZED_DIR" in script
    assert "local_dir.symlink_to(shared_dir" in script
    assert 'local_dir=str(shared_dir)' in script


def test_midtrain_continuation_launcher_does_not_restore_original_pretokens():
    script = (
        Path(__file__).resolve().parents[1]
        / "runs/clean1930s-d24-r12-ctx4096-sssl-fulltok-mix-og.sh"
    ).read_text()
    assert "HOSTED_PRETOK_REPOS" in script
    assert "active_mixture_source_dirs" in script
    assert "PRETOKENIZED_REPO" not in script
    assert "HOSTED_PRETOKENIZED_DIR" not in script
    assert "clean1930s-d24-r12-ctx4096-fulltok-v1-pretok" not in script


def test_container_smoke_requires_matching_prebuilt_lock(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    image = tmp_path / "image"
    (repo / "uv.lock").parent.mkdir(parents=True)
    (repo / "uv.lock").write_bytes(b"same-lock")
    (image / "bin").mkdir(parents=True)
    (image / "bin/python").write_bytes(b"python")
    image_lock = tmp_path / "image.lock"
    image_lock.write_bytes(b"same-lock")
    monkeypatch.setenv("NANOCHAT_PREBUILT_VENV", str(image))
    monkeypatch.setenv("NANOCHAT_PREBUILT_LOCK", str(image_lock))

    _validate_prebuilt_lock(repo)
    image_lock.write_bytes(b"stale-lock")
    with pytest.raises(RuntimeError, match="does not match"):
        _validate_prebuilt_lock(repo)


def test_gpu_preflight_cuda_version_parsing():
    assert _cuda_version_tuple("12.8") == (12, 8)
    assert _cuda_version_tuple("13.2") == (13, 2)
    assert _cuda_version_tuple(None) == (0, 0)


def test_gpu_preflight_accepts_fully_connected_nvlink():
    topology = """
        GPU0 GPU1 GPU2 GPU3 CPU Affinity NUMA Affinity GPU NUMA ID
GPU0     X   NV18 NV18 NV18 0-31 0 N/A
GPU1   NV18   X   NV18 NV18 0-31 0 N/A
GPU2   NV18 NV18   X   NV18 32-63 1 N/A
GPU3   NV18 NV18 NV18   X   32-63 1 N/A
"""
    _validate_full_nvlink_topology(topology, 4)


def test_gpu_preflight_rejects_partial_or_pcie_topology():
    topology = """
        GPU0 GPU1 GPU2 GPU3 CPU Affinity NUMA Affinity GPU NUMA ID
GPU0     X   NV12 SYS  SYS  0-31 0 N/A
GPU1   NV12   X   SYS  SYS  0-31 0 N/A
GPU2   SYS  SYS    X   NV12 32-63 1 N/A
GPU3   SYS  SYS  NV12    X  32-63 1 N/A
"""
    with pytest.raises(RuntimeError, match="fully NVLink-connected"):
        _validate_full_nvlink_topology(topology, 4)


def test_vast_image_is_locked_and_contains_no_credentials():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "dev/providers/vast/Dockerfile").read_text()
    workflow = (root / ".github/workflows/build-vast-image.yml").read_text()
    assert "cuda-12.8.1-cudnn-devel-ubuntu22.04-py310" in dockerfile
    assert "@sha256:bfb8ad72550737751fff5b5ec8998fec088080ab60fd71e35d87f136273b5652" in dockerfile
    assert "uv sync --frozen --extra gpu --no-install-project" in dockerfile
    assert "NANOCHAT_PREBUILT_LOCK=/opt/think-nano-env/uv.lock" in dockerfile
    assert "torch.__version__.split('+')[0] == '2.9.1'" in dockerfile
    assert "HF_TOKEN" not in dockerfile
    assert "WANDB_API_KEY" not in dockerfile
    assert "build-args: LOCK_SHA=${{ steps.lock.outputs.full_sha }}" in workflow
    assert "cu128-torch291-${{ steps.lock.outputs.short_sha }}" in workflow
    assert "packages: write" in workflow


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


def test_uploaded_checkpoint_pruning_keeps_only_latest_local_copy(
    tmp_path, monkeypatch
):
    experiment = make_experiment(
        tmp_path,
        monkeypatch,
        write_config(
            tmp_path / "config.json",
            artifacts={"repo": "owner/models", "keep_local_checkpoints": 1},
        ),
    )
    experiment.checkpoint_dir.mkdir(parents=True)
    for step in (100, 200):
        for path in experiment.checkpoint_files(step):
            path.write_bytes(b"checkpoint")

    experiment.prune_uploaded_checkpoints({100, 200})

    assert not any(path.exists() for path in experiment.checkpoint_files(100))
    assert all(path.exists() for path in experiment.checkpoint_files(200))


def test_distributed_checkpoint_requires_every_optimizer_rank(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOCHAT_EXPERIMENT_ROOT", str(tmp_path / "runs"))
    experiment = Experiment(
        write_config(tmp_path / "config.json"),
        nproc_per_node=4,
    )
    experiment.checkpoint_dir.mkdir(parents=True)
    (experiment.checkpoint_dir / "model_000100.pt").write_bytes(b"x")
    (experiment.checkpoint_dir / "meta_000100.json").write_text("{}")
    for rank in range(3):
        (experiment.checkpoint_dir / f"optim_000100_rank{rank}.pt").write_bytes(b"x")
    assert experiment.complete_local_steps() == []
    (experiment.checkpoint_dir / "optim_000100_rank3.pt").write_bytes(b"x")
    assert experiment.complete_local_steps() == [100]
    experiment.validate_resume_checkpoint(100)

    (experiment.checkpoint_dir / "optim_000100_rank4.pt").write_bytes(b"x")
    with pytest.raises(RuntimeError, match="optimizer ranks expected"):
        experiment.validate_resume_checkpoint(100)


def test_distributed_remote_checkpoint_requires_every_rank(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOCHAT_EXPERIMENT_ROOT", str(tmp_path / "runs"))
    experiment = Experiment(
        write_config(tmp_path / "config.json"),
        nproc_per_node=4,
    )
    prefix = experiment.remote_path(experiment.checkpoint_relative)
    files = {
        f"{prefix}/model_000100.pt",
        f"{prefix}/meta_000100.json",
        *(f"{prefix}/optim_000100_rank{rank}.pt" for rank in range(3)),
    }
    monkeypatch.setattr(experiment, "remote_files", lambda strict=False: files)
    assert experiment.complete_remote_steps(strict=True) == []
    files.add(f"{prefix}/optim_000100_rank3.pt")
    assert experiment.complete_remote_steps(strict=True) == [100]


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


def test_prepare_tokenizer_reuses_source_without_changing_fingerprint(
    tmp_path, monkeypatch
):
    source_id = "source-tokenizer-run"
    experiment = make_experiment(
        tmp_path,
        monkeypatch,
        write_config(
            tmp_path / "config.json",
            tokenizer={
                "mode": "reuse",
                "source_experiment_id": source_id,
                "vocab_size": 32768,
            },
        ),
    )
    marker = b'{"experiment_id":"source-tokenizer-run"}'
    source_paths = []
    uploads = []

    monkeypatch.setattr(experiment, "download_folder", lambda *args, **kwargs: 0)

    def fake_source_download(remote_dir, local_dir, strict=False):
        source_paths.append(remote_dir)
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "tokenizer.pkl").write_bytes(b"tokenizer")
        (local_dir / "token_bytes.pt").write_bytes(b"token bytes")
        (local_dir / "experiment_tokenizer.json").write_bytes(marker)
        return 3

    monkeypatch.setattr(
        experiment, "download_folder_from_remote_path", fake_source_download
    )
    monkeypatch.setattr(
        experiment, "upload_folder", lambda *args, **kwargs: uploads.append(args)
    )
    monkeypatch.setattr(
        experiment_module,
        "run_streaming",
        lambda *args, **kwargs: pytest.fail("tokenizer should not retrain"),
    )

    experiment.prepare_tokenizer()

    assert source_paths == [f"experiments/{source_id}/tokenizer"]
    assert (experiment.tokenizer_dir / "experiment_tokenizer.json").read_bytes() == marker
    assert uploads


def test_reuse_tokenizer_requires_distinct_source(tmp_path, monkeypatch):
    config = write_config(
        tmp_path / "config.json",
        tokenizer={"mode": "reuse", "source_experiment_id": "test-run"},
    )
    experiment = make_experiment(tmp_path, monkeypatch, config)
    with pytest.raises(ValueError, match="different"):
        experiment.validate_config()


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


def test_hosted_pretokenized_cache_validates_91_train_files(tmp_path, monkeypatch):
    config = write_config(
        tmp_path / "config.json",
        {
            "scaling_params": 1000,
            "target_param_data_ratio": 10.0,
            "total_batch_size": 100,
        },
        dataset={
            "adapter": "parquet_shards",
            "repo": "owner/data",
            "revision": "main",
        },
        tokenizer={"mode": "train", "vocab_size": 32768},
        pretokenize={"enabled": True, "require_no_wrap": True},
    )
    experiment = make_experiment(tmp_path, monkeypatch, config)
    experiment.tokenizer_dir.mkdir(parents=True)
    (experiment.tokenizer_dir / "tokenizer.pkl").write_bytes(b"tokenizer")
    experiment.pretok_dir.mkdir(parents=True)

    train_files = []
    for index in range(91):
        filename = f"train_{index:05d}.bin"
        (experiment.pretok_dir / filename).write_bytes(b"\0\0")
        train_files.append({"filename": filename, "num_tokens": 1})
    (experiment.pretok_dir / "val_00000.bin").write_bytes(b"\0\0")
    meta = {
        "source_dataset_repo": "owner/data",
        "source_revision": "main",
        "tokenizer_fingerprint": _tokenizer_fingerprint(experiment.tokenizer_dir),
        "dtype": "uint16",
        "vocab_size": 32768,
        "train_tokens": 91,
        "val_tokens": 1,
        "train_source_exhausted": False,
        "train_files": train_files,
        "val_files": [{"filename": "val_00000.bin", "num_tokens": 1}],
    }
    validated = experiment.validate_pretokenized_cache(meta)
    assert len(validated["train_files"]) == 91
    assert len(validated["val_files"]) == 1


def test_hosted_pretokenized_cache_rejects_wrong_file_size(tmp_path, monkeypatch):
    config = write_config(
        tmp_path / "config.json",
        dataset={"adapter": "parquet_shards", "repo": "owner/data", "revision": "main"},
        tokenizer={"mode": "train", "vocab_size": 32768},
    )
    experiment = make_experiment(tmp_path, monkeypatch, config)
    experiment.tokenizer_dir.mkdir(parents=True)
    (experiment.tokenizer_dir / "tokenizer.pkl").write_bytes(b"tokenizer")
    experiment.pretok_dir.mkdir(parents=True)
    (experiment.pretok_dir / "train_00000.bin").write_bytes(b"\0")
    (experiment.pretok_dir / "val_00000.bin").write_bytes(b"\0\0")
    meta = {
        "source_dataset_repo": "owner/data",
        "source_revision": "main",
        "tokenizer_fingerprint": _tokenizer_fingerprint(experiment.tokenizer_dir),
        "dtype": "uint16",
        "vocab_size": 32768,
        "train_tokens": 1,
        "val_tokens": 1,
        "train_files": [{"filename": "train_00000.bin", "num_tokens": 1}],
        "val_files": [{"filename": "val_00000.bin", "num_tokens": 1}],
    }
    with pytest.raises(RuntimeError, match="expected 2"):
        experiment.validate_pretokenized_cache(meta)


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


def test_ratio_scout_reuses_results_and_computes_ratio_and_flops(
    tmp_path, monkeypatch
):
    config_path = write_config(
        tmp_path / "config.json",
        training={
            "scaling_params": 1_000,
            "total_batch_size": 100,
            "device_batch_size": 1,
        },
        pretokenize={"enabled": True},
        wandb={"enabled": False},
    )
    experiment = make_experiment(tmp_path, monkeypatch, config_path)
    experiment.checkpoint_dir.mkdir(parents=True)
    experiment.eval_dir.mkdir(parents=True)
    experiment.pretok_dir.mkdir(parents=True)
    experiment.run_path.parent.mkdir(parents=True, exist_ok=True)
    experiment.run_path.write_text(json.dumps({"wandb_run_id": None}))

    for step in (25, 30):
        suffix = f"{step:06d}"
        (experiment.checkpoint_dir / f"model_{suffix}.pt").write_bytes(b"model")
        (experiment.checkpoint_dir / f"optim_{suffix}_rank0.pt").write_bytes(b"optim")
        (experiment.checkpoint_dir / f"meta_{suffix}.json").write_text(json.dumps({
            "step": step,
            "total_batch_size": 100,
            "loop_state": {
                "stage_training_flops": float(step * 1_000),
                "inherited_parent_flops": 0.0,
                "cumulative_pipeline_training_flops": float(step * 1_000),
            },
        }))

    scout_dir = experiment.eval_dir / "ratio_scout"
    scout_dir.mkdir()
    (scout_dir / "step_000025.json").write_text(json.dumps({
        "step": 25,
        "core_metric": 0.08,
        "centered_results": {"task": 0.08},
        "bpb": {"val": 1.2},
    }))
    (experiment.eval_dir / "core.json").write_text(json.dumps({
        "step": 30,
        "model": "base",
        "core_metric": 0.09,
        "core_results": {"task": 0.6},
        "centered_results": {"task": 0.09},
    }))
    (experiment.eval_dir / "val_bpb.json").write_text(json.dumps({
        "step": 30,
        "model": "base",
        "bpb": {"val": 1.1},
    }))

    monkeypatch.setattr(experiment, "initialize", lambda *args, **kwargs: None)
    monkeypatch.setattr(experiment, "download_folder", lambda *args, **kwargs: 0)
    uploads = []
    monkeypatch.setattr(
        experiment,
        "upload_file",
        lambda *args: uploads.append(args),
    )
    monkeypatch.setattr(
        experiment,
        "upload_folder",
        lambda *args: uploads.append(args),
    )
    monkeypatch.setattr(
        experiment_module,
        "run_streaming",
        lambda *args, **kwargs: pytest.fail("completed evaluations should be reused"),
    )

    records = experiment.evaluate_ratio_scout([30, 25])

    assert [record["step"] for record in records] == [25, 30]
    assert records[0]["realized_ratio"] == 2.5
    assert records[1]["cumulative_pipeline_training_flops"] == 30_000.0
    assert records[1]["core_metric"] == 0.09
    assert records[1]["full_val_bpb"] == 1.1
    assert json.loads((scout_dir / "step_000030.json").read_text())["step"] == 30
    assert uploads[-1][1] == "evals/ratio_scout"


def test_ratio_scout_logs_combined_metrics_to_original_wandb_run(
    tmp_path, monkeypatch
):
    config_path = write_config(
        tmp_path / "config.json",
        training={
            "scaling_params": 1_000,
            "total_batch_size": 100,
            "device_batch_size": 1,
        },
        pretokenize={"enabled": True},
        wandb={"entity": "entity", "project": "project", "name": "run"},
    )
    experiment = make_experiment(tmp_path, monkeypatch, config_path)
    experiment.checkpoint_dir.mkdir(parents=True)
    experiment.eval_dir.mkdir(parents=True)
    experiment.pretok_dir.mkdir(parents=True)
    experiment.run_path.parent.mkdir(parents=True, exist_ok=True)
    experiment.run_path.write_text(json.dumps({"wandb_run_id": "run-id"}))
    (experiment.checkpoint_dir / "model_000025.pt").write_bytes(b"model")
    (experiment.checkpoint_dir / "meta_000025.json").write_text(json.dumps({
        "step": 25,
        "total_batch_size": 100,
        "loop_state": {
            "stage_training_flops": 25_000.0,
            "inherited_parent_flops": 0.0,
            "cumulative_pipeline_training_flops": 25_000.0,
        },
    }))
    scout_dir = experiment.eval_dir / "ratio_scout"
    scout_dir.mkdir()
    (scout_dir / "step_000025.json").write_text(json.dumps({
        "step": 25,
        "core_metric": 0.08,
        "centered_results": {"task": 0.08},
        "bpb": {"val": 1.2},
    }))

    class Run:
        def __init__(self):
            self.summary = {}
            self.logged = []

        def define_metric(self, *args, **kwargs):
            pass

        def log(self, values):
            self.logged.append(values)

        def finish(self):
            pass

    run = Run()
    fake_wandb = types.SimpleNamespace(init=lambda **kwargs: run)
    monkeypatch.setitem(sys.modules, "wandb", fake_wandb)
    monkeypatch.setattr(experiment, "initialize", lambda *args, **kwargs: None)
    monkeypatch.setattr(experiment, "download_folder", lambda *args, **kwargs: 0)
    monkeypatch.setattr(experiment, "upload_folder", lambda *args, **kwargs: None)

    experiment.evaluate_ratio_scout([25])

    assert run.logged == [{
        "step": 25,
        "total_training_flops": 25_000.0,
        "stage_training_flops": 25_000.0,
        "inherited_parent_flops": 0.0,
        "cumulative_pipeline_training_flops": 25_000.0,
        "eval/realized_ratio": 2.5,
        "core_metric": 0.08,
        "eval/full_val_bpb": 1.2,
        "centered_results": {"task": 0.08},
    }]
    assert run.summary["ratio_scout_steps"] == [25]


def test_ratio30_config_horizon():
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


def notebook_code():
    repo_root = Path(__file__).resolve().parents[1]
    notebook = json.loads(
        (repo_root / "dev/colab_nanochat_experiment.ipynb").read_text()
    )
    return "\n".join(
        "".join(cell.get("source", []))
        for cell in notebook["cells"]
        if cell["cell_type"] == "code"
    )


def test_notebook_launcher_is_valid_python_and_drives_the_harness():
    repo_root = Path(__file__).resolve().parents[1]
    code = notebook_code()
    # Shell escapes are IPython syntax, not Python; everything else must compile.
    compile(
        "\n".join(
            re.sub(r"^(\s*)!.*$", r"\1pass", line) for line in code.splitlines()
        ),
        "colab_nanochat_experiment.ipynb",
        "exec",
    )
    configured = re.findall(r"CONFIG_PATH\s*=\s*'(configs/[^']+)'", code)
    assert configured, "the notebook must name the configs it launches"
    for relative in configured:
        assert (repo_root / relative).exists(), relative
    # The launcher only sets variables and calls the harness commands.
    assert set(re.findall(r"scripts\.experiment (\w[\w-]*)", code)) <= {
        "prepare", "plan", "train", "eval", "chat", "wandb-workspace",
    }
    assert "No-wrap validation passed." in code
    assert "not independent ratio experiments" in code


def test_notebook_exposes_branch_controls():
    code = notebook_code()
    # Branch point override, forwarded to the harness through the environment.
    assert "BRANCH_STEP = ''" in code
    assert "os.environ['NANOCHAT_BRANCH_STEP'] = str(BRANCH_STEP)" in code
    assert "os.environ.pop('NANOCHAT_BRANCH_STEP', None)" in code
    # The validate cell prints the parent/child table for branch configs.
    assert "_base_config.get('branch', {})" in code
    assert "branch = config.get('branch', {})" in code
    assert "if branch or 'mixture_schedule' in config:" in code
    assert 'scripts.experiment plan --config "$BASE_CONFIG_PATH"' in code


def test_posttrain_flops_include_optimization_and_forward_only_rollouts():
    per_token = 900.0
    stage = training_flops(100, per_token)
    stage += rollout_generation_flops(60, per_token)
    assert stage == 108_000.0
    assert cumulative_pipeline_flops(stage, 1_000.0) == 109_000.0


class FakeWandbRun:
    def __init__(self):
        self.defined_metrics = []
        self.summary = {}

    def define_metric(self, *args, **kwargs):
        self.defined_metrics.append((args, kwargs))


def test_compute_log_fields_include_compatibility_alias():
    fields = compute_log_fields(12, 100.0, 25.0)
    assert fields == {
        "step": 12,
        "total_training_flops": 125.0,
        "stage_training_flops": 100.0,
        "inherited_parent_flops": 25.0,
        "cumulative_pipeline_training_flops": 125.0,
    }


def test_checkpoint_compute_fields_restore_resume_state():
    fields = checkpoint_compute_fields({
        "step": 500,
        "loop_state": {
            "stage_training_flops": 20.0,
            "inherited_parent_flops": 80.0,
            "cumulative_pipeline_training_flops": 105.0,
        },
    })
    assert fields["step"] == 500
    assert fields["stage_training_flops"] == 20.0
    assert fields["inherited_parent_flops"] == 80.0
    assert fields["cumulative_pipeline_training_flops"] == 105.0
    assert fields["total_training_flops"] == 105.0


def test_fixed_batch_flops_use_completed_optimizer_steps():
    assert fixed_batch_stage_flops(10, 100, 3.0) == 3000.0
    assert fixed_batch_stage_flops(11, 100, 3.0) == 3300.0


def test_wandb_metric_and_summary_contract():
    run = FakeWandbRun()
    configure_wandb_metrics(run)
    update_wandb_lineage_summary(run, {
        "stage": "sft",
        "base_experiment_id": "base-a",
        "parent_experiment_id": "base-a",
        "parent_checkpoint_step": 500,
        "config_fingerprint": "abc",
        "tokenizer_fingerprint": "tok",
        "git_commit_sha": "sha",
        "resolved_experiment_config": {
            "dataset": {"repo": "owner/data"},
        },
    }, "sft-a")
    fields = compute_log_fields(10, 20.0, 100.0)
    update_wandb_compute_summary(run, fields)

    assert (("step",), {}) in run.defined_metrics
    assert any(args == ("pass@*",) for args, _ in run.defined_metrics)
    assert run.summary["experiment_id"] == "sft-a"
    assert run.summary["dataset"] == "owner/data"
    assert run.summary["cumulative_pipeline_training_flops"] == 120.0


def test_downstream_eval_forwards_wandb_identity(tmp_path, monkeypatch):
    config = write_config(
        tmp_path / "sft.json",
        {},
        stage="sft",
        experiment_id="recipe-a",
        parent={"base_experiment_id": "base-a", "checkpoint_step": 100},
        wandb={
            "entity": "entity",
            "project": "project",
            "name": "recipe-a",
        },
    )
    experiment = make_experiment(tmp_path, monkeypatch, config)
    experiment.checkpoint_dir.mkdir(parents=True)
    experiment.eval_dir.mkdir(parents=True)
    (experiment.checkpoint_dir / "model_000010.pt").write_bytes(b"x")
    (experiment.checkpoint_dir / "optim_000010_rank0.pt").write_bytes(b"x")
    (experiment.checkpoint_dir / "meta_000010.json").write_text("{}")
    experiment.run_path.parent.mkdir(parents=True, exist_ok=True)
    experiment.run_path.write_text(json.dumps({"wandb_run_id": "run-id"}))
    commands = []
    monkeypatch.setattr(
        experiment_module,
        "run_streaming",
        lambda command, env: commands.append(command),
    )
    monkeypatch.setattr(experiment, "build_summary", lambda: {})
    monkeypatch.setattr(experiment, "sync_metadata", lambda: None)

    experiment.evaluate()

    assert "--wandb-run-id=run-id" in commands[0]
    assert "--wandb-run-name=recipe-a" in commands[0]


# --------------------------------------------------------------------------------
# Branching: a base run that starts from another base run's weights and optimizer
# state, then trains with its own data and hyperparameters.


PARENT_BRANCH_CONFIG = {
    "schema_version": 1,
    "stage": "base",
    "experiment_id": "parent-run",
    "dataset": {"adapter": "parquet_shards", "repo": "owner/parent-data"},
    "tokenizer": {"mode": "train", "vocab_size": 32768},
    "training": {
        "depth": 12,
        "total_batch_size": 100,
        "num_iterations": 2000,
        "matrix_lr": 0.02,
    },
    "artifacts": {"repo": "owner/models"},
}


def write_branch_configs(tmp_path, monkeypatch, branch=None, **overrides):
    """Write a parent config into a fake configs/base registry plus a child config
    that branches off it, and return the child Experiment."""
    registry = tmp_path / "configs" / "base"
    registry.mkdir(parents=True, exist_ok=True)
    (registry / "parent-run.json").write_text(json.dumps(PARENT_BRANCH_CONFIG))
    monkeypatch.setattr(
        Experiment,
        "_config_registry_path",
        lambda self, stage, experiment_id: registry / f"{experiment_id}.json",
    )
    child = {
        "schema_version": 1,
        "stage": "base",
        "experiment_id": "child-run",
        "branch": {"parent_experiment_id": "parent-run", "parent_step": 1500,
                   **(branch or {})},
        "dataset": {"adapter": "parquet_shards", "repo": "owner/child-data"},
        "training": {
            "depth": 12,
            "total_batch_size": 100,
            "num_iterations": 400,
            "matrix_lr": 0.01,
        },
        "artifacts": {"repo": "owner/models"},
    }
    child.update(overrides)
    path = tmp_path / "child.json"
    path.write_text(json.dumps(child))
    return make_experiment(tmp_path, monkeypatch, path)


def test_branch_config_passes_the_parent_checkpoint_to_base_train(tmp_path, monkeypatch):
    experiment = write_branch_configs(tmp_path, monkeypatch)
    experiment.validate_config()
    assert experiment.is_branch
    assert experiment.parent_experiment_id == "parent-run"
    assert experiment.parent_checkpoint_step == 1500
    # A branch keeps its own top-level experiment tree; only the checkpoint is shared.
    assert experiment.root == tmp_path / "runs" / "child-run"
    assert experiment.hf_prefix == "experiments/child-run"
    assert experiment.branch_parent_checkpoint_dir == (
        tmp_path / "runs" / "parent-run" / "base_checkpoints"
    )

    command = experiment._base_train_command({"wandb_run_id": "run-id"})
    assert f"--init-from-checkpoint-dir={experiment.branch_parent_checkpoint_dir}" in command
    assert "--init-from-step=1500" in command
    assert "--branch-lr-schedule=branch" in command
    assert "--branch-parent-experiment-id=parent-run" in command
    assert "--no-init-optimizer" not in command
    # The horizon stays this run's own span; base_train offsets it by the branch step.
    assert "--num-iterations=400" in command


def test_branch_options_reach_the_training_command(tmp_path, monkeypatch):
    experiment = write_branch_configs(
        tmp_path,
        monkeypatch,
        branch={"lr_schedule": "continue", "load_optimizer": False},
    )
    experiment.validate_config()
    command = experiment._base_train_command({"wandb_run_id": "run-id"})
    assert "--branch-lr-schedule=continue" in command
    assert "--no-init-optimizer" in command


def test_branch_step_can_be_overridden_from_the_cli(tmp_path, monkeypatch):
    experiment = write_branch_configs(tmp_path, monkeypatch)
    override = Experiment(experiment.config_path, branch_step=900)
    assert override.branch["parent_step"] == 900
    assert "--init-from-step=900" in override._base_train_command(
        {"wandb_run_id": "run-id"}
    )


def test_branch_step_override_is_ignored_without_a_branch_block(tmp_path, monkeypatch):
    path = write_config(tmp_path / "config.json", {"target_tokens": 1000})
    monkeypatch.setenv("NANOCHAT_EXPERIMENT_ROOT", str(tmp_path / "runs"))
    experiment = Experiment(path, branch_step=900)
    assert not experiment.is_branch
    assert experiment.parent_experiment_id is None
    assert not any(
        argument.startswith(("--init-from", "--branch-", "--no-init-optimizer"))
        for argument in experiment._base_train_command({"wandb_run_id": "run-id"})
    )


def test_branch_resolves_and_pins_the_latest_parent_checkpoint(tmp_path, monkeypatch):
    experiment = write_branch_configs(tmp_path, monkeypatch, branch={"parent_step": None})
    experiment.branch.pop("parent_step")
    prefix = "experiments/parent-run/base_checkpoints"
    remote = {
        f"{prefix}/model_000500.pt",
        f"{prefix}/meta_000500.json",
        f"{prefix}/optim_000500_rank0.pt",
        f"{prefix}/model_001000.pt",
        f"{prefix}/meta_001000.json",
        # step 1000 has no optimizer shard, so it is not a complete branch point
    }
    monkeypatch.setattr(
        experiment, "remote_files", lambda strict=False, path_in_repo=None: remote
    )
    uploads = []
    monkeypatch.setattr(experiment, "upload_file", lambda *args: uploads.append(args))
    experiment.run_path.parent.mkdir(parents=True, exist_ok=True)
    experiment.run_path.write_text(json.dumps({"wandb_run_id": "run-id"}))

    assert experiment.resolve_branch_step() == 500
    # Pinned so a resumed run keeps branching from the same weights.
    assert json.loads(experiment.run_path.read_text())["branch_parent_step"] == 500
    assert uploads and uploads[0][1] == "run.json"

    later = write_branch_configs(tmp_path, monkeypatch, branch={"parent_step": None})
    later.branch.pop("parent_step")
    monkeypatch.setattr(
        later, "remote_files", lambda strict=False, path_in_repo=None: remote | {
            f"{prefix}/model_001800.pt",
            f"{prefix}/meta_001800.json",
            f"{prefix}/optim_001800_rank0.pt",
        }
    )
    assert later.resolve_branch_step() == 500


def test_branch_requires_every_optimizer_shard_for_the_world_size(tmp_path, monkeypatch):
    experiment = write_branch_configs(tmp_path, monkeypatch)
    experiment.nproc_per_node = 4
    prefix = "experiments/parent-run/base_checkpoints"
    monkeypatch.setattr(
        experiment,
        "remote_files",
        lambda strict=False, path_in_repo=None: {
            f"{prefix}/model_001500.pt",
            f"{prefix}/meta_001500.json",
            *(f"{prefix}/optim_001500_rank{rank}.pt" for rank in range(2)),
        },
    )
    with pytest.raises(RuntimeError, match="optim_001500_rank2.pt"):
        experiment.prepare_branch_parent()


def test_branch_rejects_a_parent_with_a_different_architecture(tmp_path, monkeypatch):
    experiment = write_branch_configs(tmp_path, monkeypatch)
    checkpoint_dir = experiment.branch_parent_checkpoint_dir
    checkpoint_dir.mkdir(parents=True)
    (checkpoint_dir / "model_001500.pt").write_bytes(b"model")
    (checkpoint_dir / "optim_001500_rank0.pt").write_bytes(b"optim")
    (checkpoint_dir / "meta_001500.json").write_text(json.dumps({
        "model_config": {"n_layer": 24, "n_embd": 1536, "n_head": 12, "vocab_size": 32768},
    }))
    with pytest.raises(RuntimeError, match="different architecture"):
        experiment.prepare_branch_parent()


def test_branch_reuses_the_parent_tokenizer_by_default(tmp_path, monkeypatch):
    experiment = write_branch_configs(tmp_path, monkeypatch)
    experiment.validate_config()
    assert experiment.tokenizer_spec == {
        "mode": "reuse",
        "source_experiment_id": "parent-run",
        "vocab_size": 32768,
    }


@pytest.mark.parametrize(
    "tokenizer,message",
    [
        ({"mode": "train", "vocab_size": 32768}, "must reuse its parent's tokenizer"),
        (
            {"mode": "reuse", "source_experiment_id": "someone-else"},
            "not the parent's tokenizer",
        ),
        (
            {"mode": "reuse", "source_experiment_id": "parent-run", "vocab_size": 16384},
            "does not match parent vocab_size",
        ),
    ],
)
def test_branch_rejects_an_incompatible_tokenizer(
    tmp_path, monkeypatch, tokenizer, message
):
    experiment = write_branch_configs(tmp_path, monkeypatch, tokenizer=tokenizer)
    with pytest.raises(ValueError, match=message):
        experiment.validate_config()


@pytest.mark.parametrize(
    "branch,message",
    [
        ({"parent_experiment_id": None}, "requires branch.parent_experiment_id"),
        ({"parent_experiment_id": "child-run"}, "must differ from experiment_id"),
        ({"parent_step": -1}, "non-negative integer"),
        ({"lr_schedule": "sideways"}, "lr_schedule must be one of"),
        ({"load_optimizer": "yes"}, "must be true or false"),
        ({"checkpoint_step": 10}, "Unknown keys in branch block"),
    ],
)
def test_branch_block_is_validated(tmp_path, monkeypatch, branch, message):
    experiment = write_branch_configs(tmp_path, monkeypatch, branch=branch)
    if branch.get("parent_experiment_id") is None and "parent_experiment_id" in branch:
        experiment.branch.pop("parent_experiment_id")
        experiment.branch_parent_id = None
    with pytest.raises(ValueError, match=message):
        experiment.validate_config()


def test_branch_rejects_a_model_shape_change(tmp_path, monkeypatch):
    experiment = write_branch_configs(
        tmp_path,
        monkeypatch,
        training={"depth": 24, "total_batch_size": 100, "num_iterations": 400},
    )
    with pytest.raises(ValueError, match="model shape must match the parent"):
        experiment.validate_config()


def test_branch_is_rejected_on_downstream_stages(tmp_path, monkeypatch):
    config = write_config(
        tmp_path / "sft.json",
        {"num_iterations": 1},
        stage="sft",
        experiment_id="recipe-a",
        parent={"base_experiment_id": "base-a", "checkpoint_step": 100},
        branch={"parent_experiment_id": "base-a"},
    )
    monkeypatch.setenv("NANOCHAT_EXPERIMENT_ROOT", str(tmp_path / "runs"))
    with pytest.raises(ValueError, match="only supported for base configs"):
        Experiment(config)


def test_branch_table_marks_what_this_run_changes(tmp_path, monkeypatch):
    experiment = write_branch_configs(tmp_path, monkeypatch)
    rows = dict(
        (field, (parent, child))
        for field, parent, child in experiment.branch_table_rows()
    )
    assert rows["experiment_id"] == ("parent-run", "child-run")
    # Step numbering continues from the parent: 1500 -> 1500 + 400.
    assert rows["checkpoint steps"][1] == "1,500 -> 1,900"
    assert rows["steps trained here"] == ("2,000", "400")
    assert rows["tokens trained here"] == ("200,000", "40,000")
    assert rows["data"] == ("owner/parent-data", "owner/child-data")
    assert rows["matrix_lr"] == ("0.02", "0.01")
    # Shape and tokenizer rows must be identical for the parent's weights to load,
    # and must read as identical so the table does not flag them as changes.
    assert rows["model (n_layer, dim, heads)"][0] == rows["model (n_layer, dim, heads)"][1]
    assert rows["tokenizer"] == (
        "parent-run (vocab 32,768)", "parent-run (vocab 32,768)"
    )


def test_branch_table_reports_a_continued_schedule_as_the_remaining_span(
    tmp_path, monkeypatch
):
    experiment = write_branch_configs(
        tmp_path,
        monkeypatch,
        branch={"lr_schedule": "continue"},
        training={"depth": 12, "total_batch_size": 100, "num_iterations": 2000},
    )
    rows = dict(
        (field, (parent, child))
        for field, parent, child in experiment.branch_table_rows()
    )
    # 'continue' finishes the parent's original 2000-step schedule.
    assert rows["checkpoint steps"][1] == "1,500 -> 2,000"
    assert rows["steps trained here"][1] == "500"


def test_branch_summary_records_lineage_and_inherited_flops(tmp_path, monkeypatch):
    experiment = write_branch_configs(tmp_path, monkeypatch)
    experiment.checkpoint_dir.mkdir(parents=True)
    experiment.eval_dir.mkdir(parents=True)
    experiment.tokenizer_dir.mkdir(parents=True)
    (experiment.checkpoint_dir / "model_001900.pt").write_bytes(b"x")
    (experiment.checkpoint_dir / "optim_001900_rank0.pt").write_bytes(b"x")
    (experiment.checkpoint_dir / "meta_001900.json").write_text(json.dumps({
        "step": 1900,
        "total_batch_size": 100,
        "loop_state": {
            "stage_start_step": 1500,
            "stage_training_flops": 40.0,
            "inherited_parent_flops": 150.0,
            "cumulative_pipeline_training_flops": 190.0,
        },
    }))
    experiment.pretok_dir.mkdir(parents=True)
    (experiment.pretok_dir / "meta.json").write_text(json.dumps({"train_tokens": 20_000}))
    experiment.run_path.parent.mkdir(parents=True, exist_ok=True)
    experiment.run_path.write_text(json.dumps({"wandb_run_id": "run-id"}))
    monkeypatch.setattr(experiment, "initialize", lambda *args, **kwargs: None)
    monkeypatch.setattr(experiment, "remote_summary", lambda: {})

    summary = experiment.build_summary()

    assert summary["parent_experiment_id"] == "parent-run"
    assert summary["parent_checkpoint_step"] == 1500
    assert summary["branch_parent_step"] == 1500
    assert summary["stage_training_flops"] == 40.0
    assert summary["inherited_parent_flops"] == 150.0
    assert summary["cumulative_pipeline_training_flops"] == 190.0
    # training_tokens spans the lineage; this run only drew the 400 steps after it.
    assert summary["training_tokens"] == 190_000
    assert summary["stage_training_tokens"] == 40_000
    assert summary["effective_epochs"] == 2.0


def test_from_scratch_summary_keeps_zero_inherited_flops(tmp_path, monkeypatch):
    experiment = make_experiment(
        tmp_path, monkeypatch, write_config(tmp_path / "config.json", {"target_tokens": 1000})
    )
    experiment.checkpoint_dir.mkdir(parents=True)
    experiment.eval_dir.mkdir(parents=True)
    experiment.tokenizer_dir.mkdir(parents=True)
    (experiment.checkpoint_dir / "model_000010.pt").write_bytes(b"x")
    (experiment.checkpoint_dir / "optim_000010_rank0.pt").write_bytes(b"x")
    (experiment.checkpoint_dir / "meta_000010.json").write_text(json.dumps({
        "step": 10,
        "total_batch_size": 100,
        "loop_state": {"stage_training_flops": 25.0},
    }))
    experiment.run_path.parent.mkdir(parents=True, exist_ok=True)
    experiment.run_path.write_text(json.dumps({"wandb_run_id": "run-id"}))
    monkeypatch.setattr(experiment, "initialize", lambda *args, **kwargs: None)
    monkeypatch.setattr(experiment, "remote_summary", lambda: {})

    summary = experiment.build_summary()

    assert summary["parent_experiment_id"] is None
    assert summary["parent_checkpoint_step"] is None
    assert summary["inherited_parent_flops"] == 0.0
    assert summary["cumulative_pipeline_training_flops"] == 25.0
    assert summary["training_tokens"] == 1000
    assert "branch_parent_step" not in summary


def test_base_train_accepts_every_branch_flag_the_harness_sends(tmp_path, monkeypatch):
    """Guard against drift between the two sides of the branch contract."""
    experiment = write_branch_configs(
        tmp_path, monkeypatch, branch={"load_optimizer": False}
    )
    source = (
        Path(__file__).resolve().parents[1] / "scripts/base_train.py"
    ).read_text(encoding="utf-8")
    flags = {
        argument.split("=")[0]
        for argument in experiment._base_train_command({"wandb_run_id": "run-id"})
        if isinstance(argument, str) and argument.startswith("--")
    }
    assert "--init-from-step" in flags and "--no-init-optimizer" in flags
    for flag in flags:
        assert f'"{flag}"' in source, f"scripts/base_train.py does not define {flag}"


def test_branch_test_config_only_changes_its_identity(tmp_path, monkeypatch):
    """clean1930s-d12-r12-branch-test exists to exercise branching itself: it picks
    1930s-d12-r12-4096ctx-run2 back up at step 2000 with the same data, mixture, and
    hyperparameters, so anything but a seamless continuation is the harness's fault."""
    repo_root = Path(__file__).resolve().parents[1]
    parent_path = repo_root / "configs/base/1930s-d12-r12-4096ctx-run2.json"
    child_path = repo_root / "configs/base/clean1930s-d12-r12-branch-test.json"
    parent = json.loads(parent_path.read_text())
    child = json.loads(child_path.read_text())

    branch = child["branch"]
    assert branch["parent_experiment_id"] == parent["experiment_id"]
    assert branch["parent_step"] == 2000
    # 'continue' finishes the parent's own schedule instead of starting a new one.
    assert branch["lr_schedule"] == "continue"
    assert branch["load_optimizer"] is True

    # Everything that defines the run itself is identical to the parent.
    for key in ("datasets", "mixture_schedule", "tokenizer", "pretokenize", "training",
                "artifacts", "stage", "schema_version"):
        assert child[key] == parent[key], key
    assert set(child) - set(parent) == {"branch"}

    batch = parent["training"]["total_batch_size"]
    total_steps = parent["mixture_schedule"]["total_tokens"] // batch
    assert total_steps == 2520
    # The branch trains the 520 steps the parent had left.
    assert total_steps - branch["parent_step"] == 520
    # The parent saves every 500 steps, so step 2000 is a real checkpoint.
    assert branch["parent_step"] % parent["training"]["save_every"] == 0

    monkeypatch.setenv("NANOCHAT_EXPERIMENT_ROOT", str(tmp_path / "runs"))
    experiment = Experiment(child_path)
    experiment.validate_config()
    command = experiment._base_train_command({"wandb_run_id": "run-id"})
    assert "--init-from-step=2000" in command
    assert "--branch-lr-schedule=continue" in command
    # The mixture horizon is the whole schedule; base_train starts the loop at 2000.
    assert "--num-iterations=2520" in command


def test_branch_test_config_lands_mid_mixture(tmp_path, monkeypatch):
    """Step 2000 falls inside the injection stage, so the branch must resume there
    rather than restarting the mixture at stage 0."""
    from nanochat.mixture import MixtureSchedule

    repo_root = Path(__file__).resolve().parents[1]
    child = json.loads(
        (repo_root / "configs/base/clean1930s-d12-r12-branch-test.json").read_text()
    )
    schedule = MixtureSchedule.from_config(
        child["mixture_schedule"],
        total_batch_size=child["training"]["total_batch_size"],
    )
    active = schedule.stage_for_step(child["branch"]["parent_step"])
    assert active.name == "injection"
    assert active.source == "midtrain_r30"
    # It still reaches the final decay stage before the horizon.
    assert schedule.stages[-1].start_step < schedule.total_steps


def write_mixture_config(path):
    """A base config in mixture form: per-source 'datasets' blocks and a
    mixture_schedule, with no top-level 'dataset'."""
    config = {
        "schema_version": 1,
        "stage": "base",
        "experiment_id": "test-mix",
        "datasets": {
            "original": {
                "adapter": "parquet_shards",
                "repo": "owner/original",
                "validation_shard": 472,
                "num_train_shards": 4,
            },
            "midtrain_r30": {
                "adapter": "parquet_shards",
                "repo": "owner/midtrain",
                "subfolder": "mixed/ratio_30/data",
                "validation_shard": 78,
                "num_train_shards": 2,
            },
        },
        "mixture_schedule": {
            "total_tokens": 1000,
            "max_epochs": 4,
            "stages": [
                {"name": "base", "start_tokens": 0, "source": "original"},
                {"name": "injection", "start_tokens": 600, "source": "midtrain_r30"},
            ],
        },
        "tokenizer": {"mode": "train"},
        "training": {
            "depth": 12,
            "total_batch_size": 100,
            "device_batch_size": 8,
            "eval_tokens": 40,
        },
        "artifacts": {"repo": "owner/models"},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config))
    return path


def make_mixture_experiment(tmp_path, monkeypatch):
    experiment = make_experiment(
        tmp_path, monkeypatch, write_mixture_config(tmp_path / "mix.json")
    )
    experiment.checkpoint_dir.mkdir(parents=True)
    for name in ("model_000010.pt", "optim_000010_rank0.pt"):
        (experiment.checkpoint_dir / name).write_bytes(b"x")
    (experiment.checkpoint_dir / "meta_000010.json").write_text("{}")
    experiment.tokenizer_dir.mkdir(parents=True)
    (experiment.tokenizer_dir / "tokenizer.pkl").write_bytes(b"x")
    experiment.run_path.parent.mkdir(parents=True, exist_ok=True)
    experiment.run_path.write_text(json.dumps({"wandb_run_id": "run-id"}))
    return experiment


def make_continuation_mixture_experiment(tmp_path, monkeypatch):
    path = write_mixture_config(tmp_path / "continuation-mix.json")
    config = json.loads(path.read_text())
    config["branch"] = {
        "parent_experiment_id": "parent-mix",
        "parent_step": 7,
        "lr_schedule": "continue",
        "load_optimizer": True,
    }
    # With batch=100, step 7 is inside r30: original=[0,6), r30=[6,9), r60=[9,10).
    config["mixture_schedule"]["total_tokens"] = 1000
    config["mixture_schedule"]["stages"][1]["start_tokens"] = 600
    config["mixture_schedule"]["stages"].append(
        {"name": "decay_mix", "start_tokens": 900, "source": "midtrain_r60"}
    )
    config["datasets"]["midtrain_r60"] = {
        **config["datasets"]["midtrain_r30"],
        "subfolder": "mixed/ratio_60/data",
    }
    path.write_text(json.dumps(config))
    return make_experiment(tmp_path, monkeypatch, path)


def test_continuation_mixture_skips_inherited_source_and_validates_on_r30(
    tmp_path, monkeypatch
):
    experiment = make_continuation_mixture_experiment(tmp_path, monkeypatch)

    assert experiment.mixture_start_tokens == 700
    assert experiment.active_mixture_sources == ["midtrain_r30", "midtrain_r60"]
    assert set(experiment.active_mixture_source_dirs) == {
        "midtrain_r30", "midtrain_r60",
    }
    assert experiment.eval_source == "midtrain_r30"
    assert experiment.eval_pretok_dir == experiment.base_root / "pretok_midtrain_r30"

    prepared = []
    monkeypatch.setattr(experiment, "_satisfied_mixture_sources", lambda: set())
    monkeypatch.setattr(
        experiment,
        "_prepare_dataset_into",
        lambda dataset, data_dir: prepared.append((dataset["repo"], data_dir.name)),
    )
    experiment.prepare_dataset()

    assert [name for _, name in prepared] == [
        "data_midtrain_r30", "data_midtrain_r60",
    ]
    assert not (experiment.base_root / "data_original").exists()

    command = experiment._base_train_command({"wandb_run_id": "run-id"})
    mixture_arg = next(arg for arg in command if arg.startswith("--mixture-source-dirs="))
    passed = json.loads(mixture_arg.split("=", 1)[1])
    assert set(passed) == {"midtrain_r30", "midtrain_r60"}


def test_continuation_mixture_pretokenizes_only_remaining_sources(
    tmp_path, monkeypatch
):
    experiment = make_continuation_mixture_experiment(tmp_path, monkeypatch)
    commands = []

    def fake_pretokenize(command, env):
        commands.append(command)
        output_dir = Path(command[command.index("--output-dir") + 1])
        target = int(command[command.index("--target-tokens") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "meta.json").write_text(json.dumps({
            "train_tokens": target,
            "train_source_exhausted": False,
        }))

    monkeypatch.setattr(experiment_module, "run_streaming", fake_pretokenize)
    experiment._prepare_pretokenized_mixture({
        "slack": 1.0,
        "val_tokens": 100,
        "shard_tokens": 1000,
        "tokenizer_threads": 1,
    })

    outputs = {
        Path(command[command.index("--output-dir") + 1]).name
        for command in commands
    }
    assert outputs == {"pretok_midtrain_r30", "pretok_midtrain_r60"}
    assert not (experiment.base_root / "pretok_original").exists()
    assert all(
        command[command.index("--val-tokens") + 1] == "40"
        for command in commands
    )


def test_mixture_eval_reads_first_stage_source_cache(tmp_path, monkeypatch):
    """The final BPB eval must read the same val split base_train logs as val/bpb:
    the first stage's source. A mixture run has no pretok/ or data/ of its own."""
    experiment = make_mixture_experiment(tmp_path, monkeypatch)
    assert experiment.eval_source == "original"
    assert experiment.eval_pretok_dir == experiment.base_root / "pretok_original"
    assert experiment.eval_data_dir == experiment.base_root / "data_original"

    # A prepared per-source cache is what makes the eval use the pretokenized loader.
    experiment.eval_pretok_dir.mkdir(parents=True)
    (experiment.eval_pretok_dir / "meta.json").write_text(
        json.dumps({"val_files": ["val_000000.bin"]})
    )
    assert experiment._has_pretok_val()

    commands = []
    monkeypatch.setattr(
        experiment_module, "run_streaming", lambda command, env: commands.append(command)
    )
    monkeypatch.setattr(experiment, "initialize", lambda *args, **kwargs: None)
    monkeypatch.setattr(experiment, "build_summary", lambda: {})
    monkeypatch.setattr(experiment, "sync_metadata", lambda: None)

    experiment.evaluate(eval_parts=("bpb",))

    bpb_command = commands[0]
    assert "--eval=bpb" in bpb_command
    assert "--pretokenized" in bpb_command
    assert f"--pretokenized-dir={experiment.base_root / 'pretok_original'}" in bpb_command
    assert not any(str(arg).startswith("--data-dir=") for arg in bpb_command)


def test_mixture_prepare_eval_downloads_first_source_val_shard(tmp_path, monkeypatch):
    """On a cold runtime the val shard has to come from the primary source's own
    dataset block; mixture configs have no top-level 'dataset' to read."""
    experiment = make_mixture_experiment(tmp_path, monkeypatch)

    commands = []
    monkeypatch.setattr(
        experiment_module, "run_streaming", lambda command, env: commands.append(command)
    )

    experiment.prepare_eval()

    def value_of(command, flag):
        return command[command.index(flag) + 1]

    download, pretok = commands
    assert "nanochat.dataset" in download
    assert value_of(download, "--max-shard") == "472"
    assert value_of(download, "--data-dir") == str(experiment.base_root / "data_original")
    assert value_of(download, "--base-url").endswith("owner/original/resolve/main")
    assert "scripts.pretok_think" in pretok
    assert "--val-only" in pretok
    assert value_of(pretok, "--output-dir") == str(experiment.base_root / "pretok_original")
    assert value_of(pretok, "--data-dir") == str(experiment.base_root / "data_original")


def test_workspace_uses_explicit_axes_and_filters_interrupted_runs(monkeypatch):
    panels = []

    class LinePlot:
        def __init__(self, **kwargs):
            panels.append(kwargs)

    class Section:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class RunComparer:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class RunsetSettings:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    saved = {}

    class Workspace:
        def __init__(self, **kwargs):
            saved.update(kwargs)
            self.url = "https://wandb.example/workspace"

        def save(self):
            saved["did_save"] = True

    reports_module = types.ModuleType("wandb_workspaces.reports.v2")
    reports_module.LinePlot = LinePlot
    reports_module.RunComparer = RunComparer
    workspaces_module = types.ModuleType("wandb_workspaces.workspaces")
    workspaces_module.Section = Section
    workspaces_module.RunsetSettings = RunsetSettings
    workspaces_module.Workspace = Workspace
    monkeypatch.setitem(sys.modules, "wandb_workspaces", types.ModuleType("wandb_workspaces"))
    monkeypatch.setitem(sys.modules, "wandb_workspaces.reports", types.ModuleType("wandb_workspaces.reports"))
    monkeypatch.setitem(sys.modules, "wandb_workspaces.reports.v2", reports_module)
    monkeypatch.setitem(sys.modules, "wandb_workspaces.workspaces", workspaces_module)
    monkeypatch.setattr(experiment_module, "classify_wandb_runs", lambda *args: None)

    experiment_module.create_wandb_workspace("entity", "project")

    assert saved["auto_generate_panels"] is False
    assert saved["runset_settings"].kwargs["filters"] == (
        "State != 'crashed' and State != 'killed'"
    )
    assert all(
        panel["x"] in {"step", "cumulative_pipeline_training_flops"}
        for panel in panels
    )
    assert any(
        panel.get("y") == ["eval/full_val_bpb"] for panel in panels
    )


def test_wandb_run_classification_is_non_destructive(monkeypatch):
    class Run:
        def __init__(self, state, summary, tags=()):
            self.state = state
            self.summary = summary
            self.tags = list(tags)
            self.updated = False

        def update(self):
            self.updated = True

    interrupted = Run("crashed", {})
    legacy = Run("finished", {})
    current = Run(
        "finished", {"cumulative_pipeline_training_flops": 100.0}
    )
    runs = [interrupted, legacy, current]

    class Api:
        def runs(self, path):
            assert path == "entity/project"
            return runs

    monkeypatch.setattr("wandb.Api", Api)
    experiment_module.classify_wandb_runs("entity", "project")

    assert "interrupted" in interrupted.tags
    assert "legacy" in legacy.tags
    assert current.tags == []
    assert interrupted.updated and legacy.updated
    assert not current.updated
