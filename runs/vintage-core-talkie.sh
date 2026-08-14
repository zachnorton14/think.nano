#!/bin/bash

# Full Original/Filtered/Restyled Vintage CORE for the official Talkie 1930
# 13B base checkpoint. Results and task-level progress are uploaded to
# jbduran/think.nano so the evaluation can resume after interruption.

set -euo pipefail

MODE="${1:-all}"
case "$MODE" in
    all|smoke) ;;
    *)
        echo "Usage: bash runs/vintage-core-talkie.sh {all|smoke}" >&2
        exit 2
        ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

export NANOCHAT_BASE_DIR="${NANOCHAT_BASE_DIR:-/workspace/nanochat}"
export OMP_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

if [ -n "${NANOCHAT_PREBUILT_VENV:-}" ]; then
    PYTHON="$NANOCHAT_PREBUILT_VENV/bin/python"
elif [ -x /opt/think-nano-venv/bin/python ]; then
    PYTHON=/opt/think-nano-venv/bin/python
elif [ -x .venv/bin/python ]; then
    PYTHON=.venv/bin/python
else
    echo "No think.nano Python environment found." >&2
    exit 2
fi

: "${HF_TOKEN:?HF_TOKEN must be set in the environment or .env}"
: "${WANDB_API_KEY:?WANDB_API_KEY must be set in the environment or .env}"

TALKIE_COMMIT="35317ba3a84861a84c84065bd73faf88ad19329c"
TALKIE_REVISION="b7c97680791f7fca4262c3c80b36ff7d666faab0"
EVALUATOR_COMMIT="82b7e92adf04aac6418b29e6bbca7ddfd479c462"
TALKIE_ROOT="$NANOCHAT_BASE_DIR/talkie-runtime-$TALKIE_COMMIT"
EVALUATOR_ROOT="$NANOCHAT_BASE_DIR/vintage-core-evaluator-$EVALUATOR_COMMIT"
if [ "$MODE" = "smoke" ]; then
    RESULTS_ROOT="$NANOCHAT_BASE_DIR/reference-evals/vintage-core-v1.0.0/talkie-1930-13b-base-smoke"
else
    RESULTS_ROOT="$NANOCHAT_BASE_DIR/reference-evals/vintage-core-v1.0.0/talkie-1930-13b-base"
fi
CACHE_ROOT="$NANOCHAT_BASE_DIR/reference-evals/cache"

mkdir -p "$NANOCHAT_BASE_DIR" "$CACHE_ROOT" "$RESULTS_ROOT"
export HF_HOME="$CACHE_ROOT/huggingface-home"
export HF_HUB_CACHE="$CACHE_ROOT/huggingface"
export HF_XET_CACHE="$CACHE_ROOT/xet"

free_kib="$(df -Pk "$NANOCHAT_BASE_DIR" | awk 'NR==2 {print $4}')"
if [ "$free_kib" -lt 94371840 ]; then
    echo "Need at least 90 GiB free under $NANOCHAT_BASE_DIR; found $((free_kib / 1024 / 1024)) GiB." >&2
    exit 2
fi
echo "Disk preflight PASS: $((free_kib / 1024 / 1024)) GiB free under $NANOCHAT_BASE_DIR"
nvidia-smi -L

if [ ! -e "$EVALUATOR_ROOT/.git" ]; then
    git fetch origin "$EVALUATOR_COMMIT"
    git worktree add --detach "$EVALUATOR_ROOT" "$EVALUATOR_COMMIT"
fi
test "$(git -C "$EVALUATOR_ROOT" rev-parse HEAD)" = "$EVALUATOR_COMMIT"

if [ ! -e "$TALKIE_ROOT/.git" ]; then
    git clone --filter=blob:none https://github.com/talkie-lm/talkie.git "$TALKIE_ROOT"
fi
git -C "$TALKIE_ROOT" fetch origin "$TALKIE_COMMIT" --depth 1
git -C "$TALKIE_ROOT" checkout --detach "$TALKIE_COMMIT"
test "$(git -C "$TALKIE_ROOT" rev-parse HEAD)" = "$TALKIE_COMMIT"

"$PYTHON" -c 'import huggingface_hub, jinja2, tiktoken, torch, wandb, yaml; print(f"Runtime preflight PASS: torch={torch.__version__}, CUDA={torch.version.cuda}")'

RUNNER_PATH="$REPO_ROOT/runs/vintage-core-talkie.sh"
RUNNER_SHA256="$(sha256sum "$RUNNER_PATH" | awk '{print $1}')"

MODE="$MODE" TALKIE_ROOT="$TALKIE_ROOT" TALKIE_COMMIT="$TALKIE_COMMIT" TALKIE_REVISION="$TALKIE_REVISION" EVALUATOR_ROOT="$EVALUATOR_ROOT" EVALUATOR_COMMIT="$EVALUATOR_COMMIT" RESULTS_ROOT="$RESULTS_ROOT" CACHE_ROOT="$CACHE_ROOT" RUNNER_PATH="$RUNNER_PATH" RUNNER_SHA256="$RUNNER_SHA256" PYTHONPATH="$TALKIE_ROOT/src:$EVALUATOR_ROOT/dev/vintage_core_colab${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON" -u - <<'PY'
from __future__ import annotations

import csv
import gc
import hashlib
import io
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F
import wandb
import yaml
from huggingface_hub import HfApi, hf_hub_download

mode = os.environ["MODE"]
talkie_root = Path(os.environ["TALKIE_ROOT"])
talkie_commit = os.environ["TALKIE_COMMIT"]
talkie_revision = os.environ["TALKIE_REVISION"]
evaluator_root = Path(os.environ["EVALUATOR_ROOT"])
evaluator_commit = os.environ["EVALUATOR_COMMIT"]
runner_path = Path(os.environ["RUNNER_PATH"])
runner_sha256 = os.environ["RUNNER_SHA256"]
evaluator_dir = evaluator_root / "dev" / "vintage_core_colab"
results_root = Path(os.environ["RESULTS_ROOT"])
cache_root = Path(os.environ["CACHE_ROOT"])
results_root.mkdir(parents=True, exist_ok=True)
cache_root.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(evaluator_dir))
sys.path.insert(0, str(talkie_root / "src"))

import vintage_core_eval as vc
from talkie.model import GPTConfig, TalkieModel
from talkie.tokenizer import build_tokenizer

MODEL_ID = "talkie-1930-13b-base"
MODEL_REPO = "talkie-lm/talkie-1930-13b-base"
CHECKPOINT_NAME = "final.ckpt"
VOCAB_NAME = "vocab.txt"
RESULT_REPO = "jbduran/think.nano"
BUNDLES = ["original", "filtered", "restyled"]
MAX_PER_TASK = 1 if mode == "smoke" else -1
REMOTE_PREFIX = f"evaluations/vintage-core-v1.0.0/{MODEL_ID}"
token = os.environ.get("HF_TOKEN")
api = HfApi(token=token)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def matching_result(path: Path, bundle: str) -> bool:
    if not path.is_file():
        return False
    try:
        value = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return (
        value.get("model") == MODEL_ID
        and value.get("bundle") == bundle
        and value.get("max_per_task") == MAX_PER_TASK
        and value.get("model_revision") == talkie_revision
        and value.get("runtime_revision") == talkie_commit
        and value.get("evaluator_commit") == evaluator_commit
        and value.get("runner_sha256") == runner_sha256
    )


def upload_file(path: Path, remote_path: str, message: str) -> None:
    try:
        api.upload_file(
            repo_id=RESULT_REPO,
            repo_type="model",
            path_or_fileobj=str(path),
            path_in_repo=remote_path,
            commit_message=message,
        )
    except Exception as exc:
        print(
            f"UPLOAD RETRY NEEDED for {remote_path}: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return
    print(f"PERSISTED: {remote_path}", flush=True)


def restore_remote() -> None:
    if mode == "smoke":
        return
    try:
        files = api.list_repo_files(RESULT_REPO, repo_type="model")
    except Exception as exc:
        print(f"Could not inspect prior remote results: {exc}", flush=True)
        return
    restored = 0
    for repo_path in files:
        if not repo_path.startswith(REMOTE_PREFIX + "/"):
            continue
        relative = repo_path.removeprefix(REMOTE_PREFIX + "/")
        if not (relative.endswith(".json") or relative.endswith(".csv")):
            continue
        cached = hf_hub_download(
            RESULT_REPO,
            repo_path,
            repo_type="model",
            revision="main",
            token=token,
            cache_dir=str(cache_root / "results"),
        )
        destination = results_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cached, destination)
        restored += 1
    if restored:
        print(f"Restored {restored} persisted Talkie result files", flush=True)


def persistence_preflight() -> None:
    if mode == "smoke":
        return
    payload = {
        "schema_version": 1,
        "model": MODEL_ID,
        "model_repo": MODEL_REPO,
        "model_revision": talkie_revision,
        "runtime_revision": talkie_commit,
        "evaluator_commit": evaluator_commit,
        "runner_sha256": runner_sha256,
        "bundles": BUNDLES,
        "scoring": "native Talkie BF16; continuation mean loss / exact-token LM",
        "prepend_endoftext": True,
    }
    api.upload_file(
        repo_id=RESULT_REPO,
        repo_type="model",
        path_or_fileobj=io.BytesIO((json.dumps(payload, indent=2) + "\n").encode()),
        path_in_repo=f"{REMOTE_PREFIX}/runner.json",
        commit_message="Initialize durable Talkie Vintage CORE evaluation",
    )
    api.upload_file(
        repo_id=RESULT_REPO,
        repo_type="model",
        path_or_fileobj=str(runner_path),
        path_in_repo=f"{REMOTE_PREFIX}/runner.sh",
        commit_message="Persist exact Talkie Vintage CORE runner",
    )
    print(f"Hugging Face persistence preflight PASS: {RESULT_REPO}/{REMOTE_PREFIX}", flush=True)


def memory_efficient_load(checkpoint_path: Path, device: torch.device) -> TalkieModel:
    print(f"Loading pinned Talkie checkpoint with mmap: {checkpoint_path}", flush=True)
    checkpoint = torch.load(
        checkpoint_path,
        map_location="cpu",
        mmap=True,
        weights_only=True,
    )
    if "model_state_dict" in checkpoint:
        state = checkpoint["model_state_dict"]
    elif "model" in checkpoint:
        state = checkpoint["model"]
    else:
        state = checkpoint
    state = {key.removeprefix("_orig_mod."): value for key, value in state.items()}
    config = GPTConfig(vocab_size=state["embed.weight"].shape[0])
    with torch.device("meta"):
        model = TalkieModel(config, torch.device("meta"), max_seq_len=4096)
    model.load_state_dict(state, strict=True, assign=True)
    # Non-persistent RoPE buffers were created on meta. Ignore them during the
    # streaming parameter move, then regenerate them directly on the H100.
    model._buffers["cos"] = None
    model._buffers["sin"] = None
    model = model.to(device=device, dtype=torch.bfloat16)
    model.device = device
    cos, sin = model._precompute_rotary_embeddings(4096, config.head_dim)
    model._buffers["cos"] = cos
    model._buffers["sin"] = sin
    model.eval()
    del state, checkpoint
    gc.collect()
    return model


def common_length(sequences: list[list[int]], direction: str = "left") -> int:
    minimum = min(len(sequence) for sequence in sequences)
    indices = range(minimum) if direction == "left" else range(-1, -minimum - 1, -1)
    for index, position in enumerate(indices):
        value = sequences[0][position]
        if not all(sequence[position] == value for sequence in sequences):
            return index
    return minimum


def main() -> None:
    persistence_preflight()
    restore_remote()

    bundle_registry = vc.read_json(evaluator_dir / "bundles.json")["bundles"]
    bundle_paths = vc.resolve_bundles(BUNDLES, bundle_registry, cache_root, token)

    checkpoint_path = Path(hf_hub_download(
        repo_id=MODEL_REPO,
        filename=CHECKPOINT_NAME,
        revision=talkie_revision,
        token=token,
        cache_dir=str(cache_root / "huggingface"),
    ))
    vocab_path = Path(hf_hub_download(
        repo_id=MODEL_REPO,
        filename=VOCAB_NAME,
        revision=talkie_revision,
        token=token,
        cache_dir=str(cache_root / "huggingface"),
    ))
    print(f"Pinned model artifacts PASS: {MODEL_REPO}@{talkie_revision}", flush=True)

    device = torch.device("cuda")
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is required")
    torch.set_float32_matmul_precision("high")
    model = memory_efficient_load(checkpoint_path, device)
    tokenizer = build_tokenizer(vocab_path, style="base")
    bos_id = tokenizer.encode_single_token("<|endoftext|>")
    output_weight = model.lm_head_gain(model.lm_head).detach()

    with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
        loader_logits = model(torch.tensor([[bos_id, bos_id]], dtype=torch.long, device=device))
    if loader_logits.shape != (1, model.config.vocab_size):
        raise RuntimeError(f"Unexpected loader-check output: {tuple(loader_logits.shape)}")
    print(
        f"Model loader PASS: {sum(parameter.numel() for parameter in model.parameters()):,} params; "
        f"peak {torch.cuda.max_memory_allocated() / 2**30:.1f} GiB",
        flush=True,
    )

    def encode(prompts: list[str]) -> list[list[int]]:
        return [[bos_id, *tokenizer.encode(prompt, allowed_special="all")] for prompt in prompts]

    def make_batch(item: dict[str, Any], task_meta: dict[str, Any], examples: list[dict[str, Any]]):
        task_type = task_meta["task_type"]
        delimiter = task_meta["continuation_delimiter"]
        if task_type == "multiple_choice":
            sequences = encode(vc.render_prompts_mc(item, delimiter, examples))
            start = common_length(sequences, "left")
            return sequences, [start] * len(sequences), [len(value) for value in sequences]
        if task_type == "schema":
            sequences = encode(vc.render_prompts_schema(item, delimiter, examples))
            suffix = common_length(sequences, "right")
            ends = [len(value) for value in sequences]
            return sequences, [end - suffix for end in ends], ends
        if task_type == "language_modeling":
            without, with_continuation = encode(vc.render_prompts_lm(item, delimiter, examples))
            start, end = len(without), len(with_continuation)
            if not (start < end and without == with_continuation[:start]):
                raise RuntimeError("Language-modeling prompt tokenization is not prefix stable")
            return [with_continuation], [start], [end]
        raise ValueError(f"Unsupported task type: {task_type}")

    @torch.inference_mode()
    def evaluate_example(index: int, data: list[dict[str, Any]], task_meta: dict[str, Any]) -> bool:
        item = data[index]
        examples: list[dict[str, Any]] = []
        if task_meta["num_fewshot"] > 0:
            rng = random.Random(1234 + index)
            available = [candidate for candidate in range(len(data)) if candidate != index]
            examples = [data[candidate] for candidate in rng.sample(available, task_meta["num_fewshot"])]
        sequences, starts, ends = make_batch(item, task_meta, examples)
        maximum = 4096
        cropped: list[list[int]] = []
        cropped_starts: list[int] = []
        cropped_ends: list[int] = []
        for sequence, start, end in zip(sequences, starts, ends):
            remove = max(0, len(sequence) - maximum)
            new_start = start - remove
            if new_start < 1:
                raise RuntimeError("Prompt continuation begins before the retained 4096-token window")
            cropped.append(sequence[remove:])
            cropped_starts.append(new_start)
            cropped_ends.append(end - remove)
        width = max(len(sequence) for sequence in cropped)
        input_ids = torch.full(
            (len(cropped), width),
            bos_id,
            dtype=torch.long,
            device=device,
        )
        for row, sequence in enumerate(cropped):
            input_ids[row, :len(sequence)] = torch.tensor(sequence, dtype=torch.long, device=device)

        with torch.autocast("cuda", dtype=torch.bfloat16):
            seq_len = input_ids.shape[1]
            cos_sin = model.cos[:, :seq_len], model.sin[:, :seq_len]
            hidden = model.embed(input_ids)
            hidden = F.rms_norm(hidden, (hidden.shape[-1],))
            embedded = hidden
            for block in model.blocks:
                hidden = block(embedded, hidden, cos_sin)
            hidden = F.rms_norm(hidden, (hidden.shape[-1],))

        if task_meta["task_type"] == "language_modeling":
            start, end = cropped_starts[0], cropped_ends[0]
            logits = F.linear(hidden[0, start - 1:end - 1], output_weight).float()
            targets = input_ids[0, start:end]
            return bool(torch.all(logits.argmax(dim=-1) == targets).item())

        mean_losses: list[float] = []
        for row, (start, end) in enumerate(zip(cropped_starts, cropped_ends)):
            logits = F.linear(hidden[row, start - 1:end - 1], output_weight).float()
            targets = input_ids[row, start:end]
            mean_losses.append(F.cross_entropy(logits, targets, reduction="mean").item())
        return mean_losses.index(min(mean_losses)) == item["gold"]

    for bundle_name in BUNDLES:
        output_path = results_root / f"{bundle_name}.json"
        if matching_result(output_path, bundle_name):
            print(f"Keeping completed bundle: {output_path}", flush=True)
            continue
        bundle_dir = bundle_paths[bundle_name]
        with (bundle_dir / "core.yaml").open(encoding="utf-8") as handle:
            tasks = yaml.safe_load(handle)["icl_tasks"]
        with (bundle_dir / "eval_meta_data.csv").open(encoding="utf-8") as handle:
            baselines = {
                row["Eval Task"]: float(row["Random baseline"])
                for row in csv.DictReader(handle)
            }
        progress_path = results_root / "progress" / f"{bundle_name}.json"
        if progress_path.is_file():
            progress = read_json(progress_path)
        else:
            progress = {}
        matching_progress = (
            progress.get("model") == MODEL_ID
            and progress.get("bundle") == bundle_name
            and progress.get("max_per_task") == MAX_PER_TASK
            and progress.get("model_revision") == talkie_revision
            and progress.get("runtime_revision") == talkie_commit
            and progress.get("evaluator_commit") == evaluator_commit
            and progress.get("runner_sha256") == runner_sha256
        )
        if not matching_progress:
            progress = {
                "schema_version": 1,
                "model": MODEL_ID,
                "bundle": bundle_name,
                "max_per_task": MAX_PER_TASK,
                "model_revision": talkie_revision,
                "runtime_revision": talkie_commit,
                "evaluator_commit": evaluator_commit,
                "runner_sha256": runner_sha256,
                "results": {},
                "centered_results": {},
                "task_runtime_seconds": {},
            }
        raw = {key: float(value) for key, value in progress["results"].items()}
        centered = {key: float(value) for key, value in progress["centered_results"].items()}
        task_times = {
            key: float(value) for key, value in progress["task_runtime_seconds"].items()
        }
        print(
            f"Starting {bundle_name}: {len(raw)}/{len(tasks)} tasks already complete",
            flush=True,
        )
        for task_number, task in enumerate(tasks, start=1):
            label = task["label"]
            if label in raw:
                print(f"Keeping {bundle_name}/{label} ({task_number}/{len(tasks)})", flush=True)
                continue
            path = bundle_dir / "eval_data" / task["dataset_uri"]
            with path.open(encoding="utf-8") as handle:
                data = [json.loads(line) for line in handle if line.strip()]
            random.Random(1337).shuffle(data)
            evaluation_count = min(len(data), MAX_PER_TASK) if MAX_PER_TASK > 0 else len(data)
            task_meta = {
                "task_type": task["icl_task_type"],
                "num_fewshot": task["num_fewshot"][0],
                "continuation_delimiter": task.get("continuation_delimiter", " "),
            }
            task_start = time.time()
            correct = 0
            for index in range(evaluation_count):
                correct += int(evaluate_example(index, data, task_meta))
                completed = index + 1
                if completed % 25 == 0 or completed == evaluation_count:
                    elapsed = time.time() - task_start
                    gpu = subprocess.check_output(
                        [
                            "nvidia-smi",
                            "--query-gpu=utilization.gpu,memory.used",
                            "--format=csv,noheader,nounits",
                        ],
                        text=True,
                        timeout=5,
                    ).strip()
                    print(
                        f"[{bundle_name}/{label} {completed}/{evaluation_count} | "
                        f"{elapsed / 60:.1f} min | GPU util%, memory MiB: {gpu}]",
                        flush=True,
                    )
            accuracy = correct / evaluation_count
            raw[label] = accuracy
            baseline = 0.01 * baselines[label]
            centered[label] = (accuracy - baseline) / (1.0 - baseline)
            task_times[label] = time.time() - task_start
            progress.update({
                "results": raw,
                "centered_results": centered,
                "task_runtime_seconds": task_times,
                "updated_at_unix": time.time(),
            })
            atomic_json(progress_path, progress)
            print(
                f"{bundle_name}/{label}: raw={accuracy:.6f} "
                f"centered={centered[label]:.6f} time={task_times[label]:.1f}s",
                flush=True,
            )
            if mode != "smoke":
                upload_file(
                    progress_path,
                    f"{REMOTE_PREFIX}/progress/{bundle_name}.json",
                    f"Checkpoint Talkie {bundle_name} after {label}",
                )
        result = {
            "model": MODEL_ID,
            "bundle": bundle_name,
            "max_per_task": MAX_PER_TASK,
            "core_metric": sum(centered.values()) / len(centered),
            "results": raw,
            "centered_results": centered,
            "runtime_seconds": sum(task_times.values()),
            "model_repo": MODEL_REPO,
            "model_revision": talkie_revision,
            "runtime_revision": talkie_commit,
            "evaluator_commit": evaluator_commit,
            "runner_sha256": runner_sha256,
            "scoring": "native Talkie BF16; continuation mean loss / exact-token LM",
            "prepend_endoftext": True,
        }
        atomic_json(output_path, result)
        print(f"Saved completed bundle: {output_path}", flush=True)
        if mode != "smoke":
            upload_file(
                output_path,
                f"{REMOTE_PREFIX}/{bundle_name}.json",
                f"Save Talkie {bundle_name} Vintage CORE result",
            )

    vc.write_tables(MODEL_ID, BUNDLES, results_root)
    if mode == "smoke":
        print(f"Talkie Vintage CORE smoke PASS: {results_root}", flush=True)
        return

    records = {name: read_json(results_root / f"{name}.json") for name in BUNDLES}
    common = sorted(set.intersection(*(
        set(record["centered_results"]) for record in records.values()
    )))
    if len(common) != 20:
        raise SystemExit(f"Expected 20 common tasks; found {len(common)}")
    payload: dict[str, Any] = {
        "eval/vintage_core/version": "v1.0.0",
        "eval/vintage_core/model_revision": talkie_revision,
        "eval/vintage_core/runtime_revision": talkie_commit,
    }
    for bundle, record in records.items():
        prefix = f"eval/vintage_core/{bundle}"
        payload[f"{prefix}/native_core"] = float(record["core_metric"])
        payload[f"{prefix}/common_20_core"] = sum(
            float(record["centered_results"][task]) for task in common
        ) / 20
        for task, value in record["results"].items():
            payload[f"{prefix}/accuracy/{task}"] = float(value)
        for task, value in record["centered_results"].items():
            payload[f"{prefix}/centered/{task}"] = float(value)
    run_id = hashlib.sha256(
        f"think.nano:vintage-core-v1.0.0:{MODEL_ID}:{talkie_revision}".encode()
    ).hexdigest()[:8]
    run = wandb.init(
        entity="jbduran-thinkingmachinesncsu",
        project="think.nano",
        id=run_id,
        resume="allow",
        name=f"vintage-core-{MODEL_ID}",
        group="vintage-core-reference-models",
        tags=["vintage-core", "reference-model", "talkie", MODEL_ID],
    )
    run.log(payload)
    run.summary.update(payload)
    run.finish()
    print(f"Logged Talkie Vintage CORE to W&B run {run_id}", flush=True)
    api.upload_folder(
        repo_id=RESULT_REPO,
        repo_type="model",
        folder_path=str(results_root),
        path_in_repo=REMOTE_PREFIX,
        commit_message="Finalize Talkie Vintage CORE tables",
    )
    print(f"All Talkie Vintage CORE results persisted: {RESULT_REPO}/{REMOTE_PREFIX}", flush=True)


main()
PY
