"""Prepare, generate, score, and upload a pinned multi-model IFEval suite."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from filelock import FileLock
from huggingface_hub import HfApi, hf_hub_download

from nanochat.common import get_base_dir
from scripts.experiment import Experiment, atomic_json
from scripts.ifeval_common import read_completed, read_inputs
from scripts.ifeval_official import GOOGLE_RESEARCH_REVISION, prepare


REPO_ROOT = Path(__file__).resolve().parents[1]


def run(command, env=None):
    print("Running:", " ".join(str(part) for part in command), flush=True)
    subprocess.run([str(part) for part in command], check=True, env=env)


def prepare_input_dataset(config, destination):
    """Download and checksum the suite's pinned ordered IFEval input."""
    source = config["input_dataset"]
    cached = Path(hf_hub_download(
        repo_id=source["repo"],
        filename=source["filename"],
        revision=source["revision"],
        repo_type="dataset",
        token=os.environ.get("HF_TOKEN"),
    ))
    digest = hashlib.sha256(cached.read_bytes()).hexdigest()
    if digest != source["sha256"]:
        raise RuntimeError(
            f"IFEval input checksum mismatch: expected {source['sha256']}, got {digest}"
        )
    read_inputs(cached, expected_rows=int(config["rows"]))
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copy2(cached, temporary)
    os.replace(temporary, destination)
    print(
        f"Pinned IFEval input PASS: {source['repo']}@{source['revision']} "
        f"({config['rows']} rows)",
        flush=True,
    )
    return destination


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


def generate_shards(
    model, prepared, input_path, model_dir, generation, progress_callback=None
):
    shard_count = int(generation["gpu_shards"])
    shard_paths = [model_dir / f"responses.shard-{index}.jsonl" for index in range(shard_count)]
    processes = []
    for index, output in enumerate(shard_paths):
        env = os.environ.copy()
        # A one-shard worker may already be pinned to a physical GPU by the queue
        # orchestrator. Preserve that pin; replacing it with logical index 0 would
        # accidentally move every worker back onto physical GPU 0.
        if shard_count > 1 or "CUDA_VISIBLE_DEVICES" not in env:
            env["CUDA_VISIBLE_DEVICES"] = str(index)
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
    while processes:
        if progress_callback is not None:
            try:
                progress_callback(shard_paths)
            except json.JSONDecodeError:
                # A generator may be between writing and fsyncing its latest JSONL row.
                pass
        running = []
        for command, process in processes:
            code = process.poll()
            if code is None:
                running.append((command, process))
            elif code:
                failures.append((code, command))
        processes = running
        if processes:
            time.sleep(2)
    if failures:
        raise RuntimeError(f"IFEval generation shard failures: {failures}")
    if progress_callback is not None:
        progress_callback(shard_paths)
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


def export_per_question_scores(
    config, input_path, score_root, export_root=None, allow_partial=False
):
    """Export join-friendly long and wide records with strict and loose scores."""
    inputs = read_jsonl(input_path)
    export_root = Path(export_root or score_root)
    expected_rows = int(config["rows"])
    if len(inputs) != expected_rows:
        raise RuntimeError(
            f"IFEval input has {len(inputs)} rows, expected {expected_rows}"
        )

    scored_models = {}
    per_model_rows = {}
    for model in config["models"]:
        model_id = model["id"]
        model_dir = Path(score_root) / model_id
        strict_path = model_dir / "eval_results_strict.jsonl"
        loose_path = model_dir / "eval_results_loose.jsonl"
        if not strict_path.exists() and not loose_path.exists() and allow_partial:
            per_model_rows[model_id] = 0
            continue
        strict_rows = read_jsonl(strict_path)
        loose_rows = read_jsonl(loose_path)
        valid_count = len(strict_rows) == len(loose_rows)
        valid_count = valid_count and (
            len(strict_rows) <= expected_rows if allow_partial
            else len(strict_rows) == expected_rows
        )
        if not valid_count:
            raise RuntimeError(
                f"{model_id} has {len(strict_rows)} strict and {len(loose_rows)} "
                f"loose rows; expected matching counts up to {expected_rows}"
            )
        per_model_rows[model_id] = len(strict_rows)
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
            if question_index >= len(strict_rows):
                continue
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
                    "input_dataset": config["input_dataset"],
                    **question,
                    "model_id": model_id,
                    "backend": model["backend"],
                    **scores,
                }
            )
        if wide_models:
            wide_rows.append(
                {
                    "schema_version": 1,
                    "suite_id": config["suite_id"],
                    "official_ifeval_revision": config["official_ifeval_revision"],
                    "input_dataset": config["input_dataset"],
                    **question,
                    "models": wide_models,
                }
            )

    long_path = export_root / "per_question_long.jsonl"
    wide_path = export_root / "per_question_wide.jsonl"
    atomic_jsonl(long_path, long_rows)
    atomic_jsonl(wide_path, wide_rows)
    manifest = {
        "schema_version": 1,
        "suite_id": config["suite_id"],
        "official_ifeval_revision": config["official_ifeval_revision"],
        "input_dataset": config["input_dataset"],
        "questions": len(inputs),
        "questions_with_scores": len(wide_rows),
        "models": [model["id"] for model in config["models"]],
        "long_rows": len(long_rows),
        "expected_long_rows": len(inputs) * len(config["models"]),
        "complete": len(long_rows) == len(inputs) * len(config["models"]),
        "per_model_rows": per_model_rows,
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
    atomic_json(export_root / "per_question_manifest.json", manifest)
    return manifest


def completed_prefix(input_path, shard_paths, model_id):
    inputs = read_inputs(input_path)
    completed = {}
    for shard_path in shard_paths:
        for key, row in read_completed(shard_path, model_id).items():
            if key in completed:
                raise RuntimeError(f"IFEval key {key} appears in multiple shards")
            completed[key] = row
    prefix = []
    for source in inputs:
        key = int(source["key"])
        result = completed.get(key)
        if result is None:
            break
        if result.get("prompt") != source["prompt"]:
            raise RuntimeError(f"Prompt mismatch for IFEval key {key}")
        prefix.append(result)
    return prefix


def stage_model_scores(model_dir, publish_root, model_id):
    destination = Path(publish_root) / model_id
    destination.mkdir(parents=True, exist_ok=True)
    for filename in (
        "responses.jsonl",
        "eval_results_strict.jsonl",
        "eval_results_loose.jsonl",
        "summary.json",
    ):
        source = Path(model_dir) / filename
        temporary = destination / f"{filename}.tmp"
        shutil.copy2(source, temporary)
        os.replace(temporary, destination / filename)


def upload_results(config, publish_root, completed_model_id, completed_questions):
    artifacts = config["artifacts"]
    repo_type = artifacts.get("repo_type", "model")
    api = HfApi(token=os.environ.get("HF_TOKEN"))
    api.create_repo(artifacts["repo"], repo_type=repo_type, exist_ok=True)
    api.upload_folder(
        repo_id=artifacts["repo"],
        repo_type=repo_type,
        folder_path=publish_root,
        path_in_repo=artifacts["path"],
        commit_message=(
            f"Upload {config['suite_id']} through {completed_model_id} "
            f"question {completed_questions}"
        ),
    )
    print(
        f"Uploaded {completed_model_id} through question {completed_questions} to "
        f"https://huggingface.co/datasets/{artifacts['repo']}/tree/main/"
        f"{artifacts['path']}",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", default="configs/ifeval/four-models-mini120-v1.json"
    )
    parser.add_argument("--no-upload", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--model-id",
        action="append",
        default=None,
        help="run only this configured model; may be repeated",
    )
    parser.add_argument(
        "--gpu-shards",
        type=int,
        default=None,
        help="override generation shards (the queue uses one shard per GPU worker)",
    )
    args = parser.parse_args()
    config = json.loads((REPO_ROOT / args.config).read_text())
    if args.gpu_shards is not None:
        config["generation"] = dict(config["generation"])
        config["generation"]["gpu_shards"] = args.gpu_shards
    if config["official_ifeval_revision"] != GOOGLE_RESEARCH_REVISION:
        raise ValueError("Suite config and scorer pin different IFEval revisions")
    source = config.get("input_dataset", {})
    required_source_fields = {"repo", "revision", "filename", "sha256"}
    if set(source) != required_source_fields:
        raise ValueError(
            f"input_dataset must contain exactly {sorted(required_source_fields)}"
        )
    if int(config["rows"]) != 120:
        raise ValueError("This suite requires the complete 120-row IFEval mini subset")
    upload_every = int(config.get("upload_every_questions", 0))
    if upload_every != 100:
        raise ValueError("The suite must publish progress every 100 IFEval questions")
    gpu_shards = int(config["generation"]["gpu_shards"])
    if gpu_shards not in {1, 2}:
        raise ValueError("IFEval generation requires one or two GPU shards")
    models = config.get("models", [])
    if len(models) != 4 or len({model["id"] for model in models}) != 4:
        raise ValueError("The suite must contain exactly four unique models")
    expected_model_ids = [
        "d32-c3rv3",
        "hla-gpt1900",
        "d32-modern-sft",
        "karpathy-d34-modern-sft",
    ]
    if [model["id"] for model in models] != expected_model_ids:
        raise ValueError(
            f"Suite models must be exactly {expected_model_ids}; Talkie is excluded"
        )
    supported = {"nanochat-experiment", "nanochat-flat-hf"}
    for model in models:
        if model.get("backend") not in supported:
            raise ValueError(f"Unknown backend for {model.get('id')!r}")
        if model["backend"] == "nanochat-experiment" and not (
            REPO_ROOT / model["config"]
        ).exists():
            raise ValueError(f"Missing experiment config {model['config']}")
    requested_model_ids = args.model_id or expected_model_ids
    unknown_model_ids = sorted(set(requested_model_ids) - set(expected_model_ids))
    if unknown_model_ids:
        raise ValueError(f"Unknown requested model IDs: {unknown_model_ids}")
    if len(set(requested_model_ids)) != len(requested_model_ids):
        raise ValueError("Requested model IDs must be unique")
    selected_models = [
        model for model in models if model["id"] in set(requested_model_ids)
    ]
    if args.validate_only:
        print(json.dumps(config, indent=2))
        print("IFEval suite configuration PASS")
        return

    import torch
    if not torch.cuda.is_available() or torch.cuda.device_count() < gpu_shards:
        raise RuntimeError(
            f"The suite requires {gpu_shards} visible CUDA GPU(s) for this worker"
        )

    base_dir = Path(os.environ.get("NANOCHAT_BASE_DIR", get_base_dir()))
    experiment_root = Path(
        os.environ.get("NANOCHAT_EXPERIMENT_ROOT", base_dir / "experiments")
    )
    output_root = base_dir / "ifeval" / config["suite_id"]
    publish_root = output_root / "publish"
    external_root = base_dir / "external"
    official_root = external_root / f"ifeval-google-{GOOGLE_RESEARCH_REVISION[:12]}"
    output_root.mkdir(parents=True, exist_ok=True)
    state_lock = FileLock(str(output_root / ".suite-state.lock"))
    external_root.mkdir(parents=True, exist_ok=True)
    comparison_path = publish_root / "comparison.json"
    progress_path = publish_root / "progress.json"
    upload_state_path = output_root / "confirmed_uploads.json"

    def load_comparison():
        if not comparison_path.exists():
            return {"schema_version": 1, "suite": config, "models": {}}
        resolved = json.loads(comparison_path.read_text())
        if resolved.get("suite", {}).get("suite_id") != config["suite_id"]:
            raise RuntimeError("Existing IFEval comparison belongs to another suite")
        resolved["suite"] = config
        return resolved

    def load_progress():
        if not progress_path.exists():
            return {
                "schema_version": 1,
                "suite_id": config["suite_id"],
                "upload_every_questions": upload_every,
                "total_questions_per_model": int(config["rows"]),
                "models": {},
            }
        progress = json.loads(progress_path.read_text())
        if progress.get("suite_id") != config["suite_id"]:
            raise RuntimeError("Existing IFEval progress belongs to another suite")
        return progress

    def load_upload_state():
        if not upload_state_path.exists():
            return {
                "schema_version": 1,
                "suite_id": config["suite_id"],
                "models": {},
            }
        upload_state = json.loads(upload_state_path.read_text())
        if upload_state.get("suite_id") != config["suite_id"]:
            raise RuntimeError("Existing upload state belongs to another suite")
        return upload_state

    # Concurrent one-GPU workers share the official input cache and publication
    # files. Prepare and initialize them under the same cross-process lock.
    with state_lock:
        prepare(official_root)
        input_path = prepare_input_dataset(
            config, output_root / "input" / "ifeval-mini-120.jsonl"
        )
        publish_root.mkdir(parents=True, exist_ok=True)
        atomic_json(comparison_path, load_comparison())
        atomic_json(progress_path, load_progress())
        atomic_json(upload_state_path, load_upload_state())

    milestones = list(range(upload_every, int(config["rows"]), upload_every))
    milestones.append(int(config["rows"]))

    for model in selected_models:
        print(f"\n=== IFEval: {model['id']} ===", flush=True)
        if model["backend"] == "nanochat-experiment":
            prepared = prepare_experiment(model)
        elif model["backend"] == "nanochat-flat-hf":
            prepared = prepare_flat(model, experiment_root)
        else:
            raise ValueError(f"Unknown backend {model['backend']!r}")
        model_dir = output_root / model["id"]
        model_dir.mkdir(parents=True, exist_ok=True)
        responses = model_dir / "responses.jsonl"
        with state_lock:
            resume_state = load_progress() if args.no_upload else load_upload_state()
            published_questions = int(
                resume_state.get("models", {})
                .get(model["id"], {})
                .get("completed_questions", 0)
            )

        def publish_progress(shard_paths):
            nonlocal published_questions
            prefix = completed_prefix(input_path, shard_paths, model["id"])
            ready = [
                milestone for milestone in milestones
                if published_questions < milestone <= len(prefix)
            ]
            for milestone in ready:
                # Scoring is quick relative to generation. Serialize it with state
                # updates/uploads so another GPU worker cannot export a half-written
                # score file or overwrite a stale comparison/progress document.
                with state_lock:
                    atomic_jsonl(responses, prefix[:milestone])
                    run([
                        sys.executable, "-u", "-m", "scripts.ifeval_official", "score",
                        "--official-root", official_root,
                        "--input", input_path,
                        "--predictions", responses,
                        "--output-dir", model_dir,
                        "--model-id", model["id"],
                        "--allow-partial",
                    ])
                    summary = json.loads((model_dir / "summary.json").read_text())
                    resolved = load_comparison()
                    resolved["models"][model["id"]] = {
                        "source": model,
                        "prepared": prepared,
                        "completed_questions": milestone,
                        "complete": milestone == int(config["rows"]),
                        "strict": summary["strict"],
                        "loose": summary["loose"],
                    }
                    atomic_json(comparison_path, resolved)
                    stage_model_scores(model_dir, publish_root, model["id"])
                    manifest = export_per_question_scores(
                        config,
                        input_path,
                        output_root,
                        export_root=publish_root,
                        allow_partial=True,
                    )
                    progress = load_progress()
                    progress["models"][model["id"]] = {
                        "completed_questions": milestone,
                        "total_questions": int(config["rows"]),
                        "complete": milestone == int(config["rows"]),
                    }
                    progress["completed_model_question_rows"] = manifest["long_rows"]
                    progress["expected_model_question_rows"] = manifest[
                        "expected_long_rows"
                    ]
                    progress["complete"] = manifest["complete"]
                    atomic_json(progress_path, progress)
                    print(
                        f"Published local score snapshot for {model['id']}: "
                        f"{milestone}/{config['rows']} questions; "
                        f"{manifest['long_rows']}/{manifest['expected_long_rows']} "
                        "suite rows available",
                        flush=True,
                    )
                    if not args.no_upload:
                        upload_results(
                            config, publish_root, model["id"], milestone
                        )
                        upload_state = load_upload_state()
                        upload_state["models"][model["id"]] = {
                            "completed_questions": milestone,
                            "total_questions": int(config["rows"]),
                            "complete": milestone == int(config["rows"]),
                        }
                        atomic_json(upload_state_path, upload_state)
                published_questions = milestone

        generate_shards(
            model,
            prepared,
            input_path,
            model_dir,
            config["generation"],
            progress_callback=publish_progress,
        )
        if published_questions != int(config["rows"]):
            raise RuntimeError(
                f"{model['id']} ended with only {published_questions} published rows"
            )

    with state_lock:
        manifest = json.loads((publish_root / "per_question_manifest.json").read_text())
    print(
        f"Exported {manifest['long_rows']} model-question scores for "
        f"{manifest['questions']} questions",
        flush=True,
    )


if __name__ == "__main__":
    main()
