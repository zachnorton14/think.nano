"""Prepare, generate, score, and upload the pinned five-model IFEval suite."""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

from nanochat.common import get_base_dir
from scripts.experiment import Experiment, atomic_json
from scripts.ifeval_official import GOOGLE_RESEARCH_REVISION, prepare


REPO_ROOT = Path(__file__).resolve().parents[1]


def run(command, env=None):
    print("Running:", " ".join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], check=True, env=env)


def prepare_external_parent_tokenizer(experiment, model):
    tokenizer_files = (
        experiment.tokenizer_dir / "tokenizer.pkl",
        experiment.tokenizer_dir / "token_bytes.pt",
    )
    if all(path.exists() and path.stat().st_size > 0 for path in tokenizer_files):
        return
    parent_config = REPO_ROOT / "configs/base" / f"{model['parent_experiment_id']}.json"
    if not parent_config.exists():
        return
    source = json.loads(parent_config.read_text()).get("external_source")
    if not source:
        return
    experiment.tokenizer_dir.mkdir(parents=True, exist_ok=True)
    for remote_name, local_name in (
        (source.get("tokenizer_file", "tokenizer.pkl"), "tokenizer.pkl"),
        (source.get("token_bytes_file", "token_bytes.pt"), "token_bytes.pt"),
    ):
        cached = hf_hub_download(
            source["repo"],
            remote_name,
            revision=source["revision"],
            token=os.environ.get("HF_TOKEN"),
        )
        destination = experiment.tokenizer_dir / local_name
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copy2(cached, temporary)
        os.replace(temporary, destination)


def prepare_experiment(model):
    experiment = Experiment(
        REPO_ROOT / model["config"],
        parent_experiment_id=model["parent_experiment_id"],
        parent_step=int(model["parent_step"]),
        nproc_per_node=1,
    )
    experiment.initialize_for_inference()
    prepare_external_parent_tokenizer(experiment, model)
    experiment._ensure_tokenizer()
    local = experiment.complete_local_steps()
    remote = experiment.complete_remote_steps(strict=True)
    steps = sorted(set(local) | set(remote))
    if not steps:
        raise RuntimeError(f"No complete checkpoint found for {model['id']}")
    step = steps[-1]
    if step not in local:
        experiment.download_step(step, include_optimizer=False)
    return {
        "checkpoint_dir": str(experiment.checkpoint_dir),
        "tokenizer_dir": str(experiment.tokenizer_dir),
        "step": step,
    }


def prepare_flat(model, experiment_root):
    command = [
        sys.executable, "-u", "-m", "scripts.import_flat_nanochat_model",
        "--repo-id", model["repo_id"],
        "--revision", model["revision"],
        "--experiment-id", model["experiment_id"],
        "--step", str(model["step"]),
        "--model-file", model["model_file"],
        "--meta-file", model["meta_file"],
        "--tokenizer-file", model["tokenizer_file"],
        "--token-bytes-file", model["token_bytes_file"],
        "--architecture", model["architecture"],
    ]
    run(command)
    root = experiment_root / model["experiment_id"]
    return {
        "checkpoint_dir": str(root / "base_checkpoints"),
        "tokenizer_dir": str(root / "tokenizer"),
        "step": int(model["step"]),
    }


def prepare_talkie(model, external_root, hf_cache):
    checkout = external_root / "talkie"
    if not checkout.exists():
        run(["git", "clone", model["repo_url"], checkout])
    actual_remote = subprocess.check_output(
        ["git", "-C", str(checkout), "remote", "get-url", "origin"], text=True
    ).strip()
    if actual_remote.rstrip("/") != model["repo_url"].rstrip("/"):
        raise RuntimeError(f"Talkie checkout has unexpected origin {actual_remote!r}")
    run(["git", "-C", checkout, "fetch", "origin", model["revision"]])
    run(["git", "-C", checkout, "checkout", "--detach", model["revision"]])
    head = subprocess.check_output(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != model["revision"]:
        raise RuntimeError(f"Talkie resolved to {head}, expected {model['revision']}")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(checkout / "src") + os.pathsep + env.get("PYTHONPATH", "")
    run(
        [
            sys.executable, "-u", "-c",
            (
                "from talkie import download_model; "
                f"print(download_model('talkie-1930-13b-it', cache_dir={str(hf_cache)!r}))"
            ),
        ],
        env=env,
    )
    return {"checkout": str(checkout), "cache_dir": str(hf_cache)}


def generate_shards(model, prepared, input_path, model_dir, generation):
    shard_count = int(generation["gpu_shards"])
    shard_paths = [model_dir / f"responses.shard-{index}.jsonl" for index in range(shard_count)]
    processes = []
    for index, output in enumerate(shard_paths):
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = str(index)
        if model["backend"] == "talkie-official":
            env["PYTHONPATH"] = (
                str(Path(prepared["checkout"]) / "src")
                + os.pathsep
                + env.get("PYTHONPATH", "")
            )
            command = [
                sys.executable, "-u", "-m", "scripts.ifeval_generate_talkie",
                "--input", input_path,
                "--output", output,
                "--model-id", model["id"],
                "--cache-dir", prepared["cache_dir"],
            ]
        else:
            command = [
                sys.executable, "-u", "-m", "scripts.ifeval_generate_nanochat",
                "--input", input_path,
                "--output", output,
                "--model-id", model["id"],
                "--checkpoint-dir", prepared["checkpoint_dir"],
                "--tokenizer-dir", prepared["tokenizer_dir"],
                "--step", str(prepared["step"]),
            ]
        command.extend([
            "--max-tokens", str(generation["max_tokens"]),
            "--shard-index", str(index),
            "--shard-count", str(shard_count),
        ])
        print("Starting:", " ".join(str(part) for part in command), flush=True)
        processes.append((command, subprocess.Popen([str(part) for part in command], env=env)))
    failures = []
    for command, process in processes:
        code = process.wait()
        if code:
            failures.append((code, command))
    if failures:
        raise RuntimeError(f"IFEval generation shard failures: {failures}")
    return shard_paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", default="configs/ifeval/five-models-v1.json"
    )
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    config = json.loads((REPO_ROOT / args.config).read_text())
    if config["official_ifeval_revision"] != GOOGLE_RESEARCH_REVISION:
        raise ValueError("Suite config and scorer pin different IFEval revisions")
    if int(config["rows"]) != 541:
        raise ValueError("This pipeline requires the complete 541-row IFEval")
    if int(config["generation"]["gpu_shards"]) != 2:
        raise ValueError("The Vast pipeline is pinned to exactly two GPU shards")
    models = config.get("models", [])
    if len(models) != 5 or len({model["id"] for model in models}) != 5:
        raise ValueError("The suite must contain exactly five unique models")
    supported = {"nanochat-experiment", "nanochat-flat-hf", "talkie-official"}
    for model in models:
        if model.get("backend") not in supported:
            raise ValueError(f"Unknown backend for {model.get('id')!r}")
        if model["backend"] == "nanochat-experiment" and not (
            REPO_ROOT / model["config"]
        ).exists():
            raise ValueError(f"Missing experiment config {model['config']}")
    if args.validate_only:
        print(json.dumps(config, indent=2))
        print("IFEval suite configuration PASS")
        return

    import torch
    if not torch.cuda.is_available() or torch.cuda.device_count() < 2:
        raise RuntimeError("The suite requires two visible CUDA GPUs")

    base_dir = Path(os.environ.get("NANOCHAT_BASE_DIR", get_base_dir()))
    experiment_root = Path(
        os.environ.get("NANOCHAT_EXPERIMENT_ROOT", base_dir / "experiments")
    )
    output_root = base_dir / "ifeval" / config["suite_id"]
    external_root = base_dir / "external"
    official_root = external_root / f"ifeval-google-{GOOGLE_RESEARCH_REVISION[:12]}"
    hf_cache = Path(os.environ.get("HF_HOME", base_dir / "huggingface"))
    external_root.mkdir(parents=True, exist_ok=True)
    package = prepare(official_root)
    input_path = package / "data/input_data.jsonl"
    hf_cache.mkdir(parents=True, exist_ok=True)
    resolved = {"schema_version": 1, "suite": config, "models": {}}

    for model in config["models"]:
        print(f"\n=== IFEval: {model['id']} ===", flush=True)
        if model["backend"] == "nanochat-experiment":
            prepared = prepare_experiment(model)
        elif model["backend"] == "nanochat-flat-hf":
            prepared = prepare_flat(model, experiment_root)
        elif model["backend"] == "talkie-official":
            prepared = prepare_talkie(model, external_root, hf_cache)
        else:
            raise ValueError(f"Unknown backend {model['backend']!r}")
        model_dir = output_root / model["id"]
        model_dir.mkdir(parents=True, exist_ok=True)
        shards = generate_shards(
            model, prepared, input_path, model_dir, config["generation"]
        )
        responses = model_dir / "responses.jsonl"
        run([
            sys.executable, "-u", "-m", "scripts.ifeval_official", "merge",
            "--input", input_path,
            "--shard", shards[0],
            "--shard", shards[1],
            "--output", responses,
            "--model-id", model["id"],
        ])
        run([
            sys.executable, "-u", "-m", "scripts.ifeval_official", "score",
            "--official-root", official_root,
            "--predictions", responses,
            "--output-dir", model_dir,
            "--model-id", model["id"],
        ])
        summary = json.loads((model_dir / "summary.json").read_text())
        resolved["models"][model["id"]] = {
            "source": model,
            "prepared": prepared,
            "strict": summary["strict"],
            "loose": summary["loose"],
        }
        atomic_json(output_root / "comparison.json", resolved)

    if not args.no_upload:
        artifacts = config["artifacts"]
        api = HfApi(token=os.environ.get("HF_TOKEN"))
        api.create_repo(artifacts["repo"], repo_type="model", exist_ok=True)
        api.upload_folder(
            repo_id=artifacts["repo"],
            repo_type="model",
            folder_path=output_root,
            path_in_repo=artifacts["path"],
            commit_message=f"Upload {config['suite_id']} IFEval results",
        )
        print(
            f"Uploaded results to https://huggingface.co/{artifacts['repo']}/tree/main/"
            f"{artifacts['path']}"
        )


if __name__ == "__main__":
    main()
