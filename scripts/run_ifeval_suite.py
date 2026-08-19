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


def read_jsonl(path):
    with Path(path).open() as handle:
        return [json.loads(line) for line in handle if line.strip()]


def atomic_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def export_per_question_scores(config, input_path, output_root):
    """Export join-friendly long and wide records with strict and loose scores."""
    inputs = read_jsonl(input_path)
    expected_rows = int(config["rows"])
    if len(inputs) != expected_rows:
        raise RuntimeError(
            f"Official IFEval input has {len(inputs)} rows, expected {expected_rows}"
        )

    scored_models = {}
    for model in config["models"]:
        model_id = model["id"]
        model_dir = Path(output_root) / model_id
        strict_rows = read_jsonl(model_dir / "eval_results_strict.jsonl")
        loose_rows = read_jsonl(model_dir / "eval_results_loose.jsonl")
        if len(strict_rows) != expected_rows or len(loose_rows) != expected_rows:
            raise RuntimeError(
                f"{model_id} has {len(strict_rows)} strict and {len(loose_rows)} "
                f"loose rows; expected {expected_rows} of each"
            )
        scored_models[model_id] = (model, strict_rows, loose_rows)

    long_rows = []
    wide_rows = []
    for question_index, official in enumerate(inputs):
        instruction_ids = official["instruction_id_list"]
        question = {
            "question_index": question_index,
            "question_key": official["key"],
            "prompt": official["prompt"],
            "instruction_id_list": instruction_ids,
            "instruction_kwargs": official["kwargs"],
        }
        wide_models = {}
        for model_id, (model, strict_rows, loose_rows) in scored_models.items():
            strict = strict_rows[question_index]
            loose = loose_rows[question_index]
            for mode, result in (("strict", strict), ("loose", loose)):
                if result.get("prompt") != official["prompt"]:
                    raise RuntimeError(
                        f"{model_id} {mode} prompt mismatch at row {question_index}"
                    )
                if result.get("instruction_id_list") != instruction_ids:
                    raise RuntimeError(
                        f"{model_id} {mode} instruction mismatch at row "
                        f"{question_index}"
                    )
                passes = result.get("follow_instruction_list")
                if not isinstance(passes, list) or len(passes) != len(instruction_ids):
                    raise RuntimeError(
                        f"{model_id} {mode} has invalid instruction scores at row "
                        f"{question_index}"
                    )
            if strict.get("response") != loose.get("response"):
                raise RuntimeError(
                    f"{model_id} strict/loose response mismatch at row {question_index}"
                )

            strict_passes = [bool(value) for value in strict["follow_instruction_list"]]
            loose_passes = [bool(value) for value in loose["follow_instruction_list"]]
            scores = {
                "response": strict["response"],
                "strict_correct": bool(strict["follow_all_instructions"]),
                "loose_correct": bool(loose["follow_all_instructions"]),
                "strict_instruction_passes": strict_passes,
                "loose_instruction_passes": loose_passes,
                "strict_failed_instruction_ids": [
                    instruction_id
                    for instruction_id, passed in zip(instruction_ids, strict_passes)
                    if not passed
                ],
                "loose_failed_instruction_ids": [
                    instruction_id
                    for instruction_id, passed in zip(instruction_ids, loose_passes)
                    if not passed
                ],
            }
            wide_models[model_id] = scores
            long_rows.append(
                {
                    "schema_version": 1,
                    "suite_id": config["suite_id"],
                    "official_ifeval_revision": config["official_ifeval_revision"],
                    **question,
                    "model_id": model_id,
                    "backend": model["backend"],
                    **scores,
                }
            )
        wide_rows.append(
            {
                "schema_version": 1,
                "suite_id": config["suite_id"],
                "official_ifeval_revision": config["official_ifeval_revision"],
                **question,
                "models": wide_models,
            }
        )

    long_path = Path(output_root) / "per_question_long.jsonl"
    wide_path = Path(output_root) / "per_question_wide.jsonl"
    atomic_jsonl(long_path, long_rows)
    atomic_jsonl(wide_path, wide_rows)
    manifest = {
        "schema_version": 1,
        "suite_id": config["suite_id"],
        "official_ifeval_revision": config["official_ifeval_revision"],
        "questions": len(inputs),
        "models": [model["id"] for model in config["models"]],
        "long_rows": len(long_rows),
        "generation": config["generation"],
        "files": {
            "per_question_long.jsonl": "One row per question and model; use this for filtering and joins.",
            "per_question_wide.jsonl": "One row per question with all model results nested by model ID.",
        },
        "score_meanings": {
            "strict_correct": "Every requested instruction passed the official strict checker.",
            "loose_correct": "Every requested instruction passed at least one official loose transformation.",
            "instruction_passes": "Boolean results aligned with instruction_id_list.",
        },
    }
    atomic_json(Path(output_root) / "per_question_manifest.json", manifest)
    return manifest


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

    manifest = export_per_question_scores(config, input_path, output_root)
    print(
        f"Exported {manifest['long_rows']} model-question scores for "
        f"{manifest['questions']} questions",
        flush=True,
    )

    if not args.no_upload:
        artifacts = config["artifacts"]
        repo_type = artifacts.get("repo_type", "model")
        api = HfApi(token=os.environ.get("HF_TOKEN"))
        api.create_repo(artifacts["repo"], repo_type=repo_type, exist_ok=True)
        api.upload_folder(
            repo_id=artifacts["repo"],
            repo_type=repo_type,
            folder_path=output_root,
            path_in_repo=artifacts["path"],
            commit_message=f"Upload {config['suite_id']} IFEval results",
        )
        repo_kind = "datasets" if repo_type == "dataset" else repo_type
        print(
            f"Uploaded results to https://huggingface.co/{repo_kind}/"
            f"{artifacts['repo']}/tree/main/{artifacts['path']}"
        )


if __name__ == "__main__":
    main()
