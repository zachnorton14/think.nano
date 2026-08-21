#!/bin/bash

# Full Original/Filtered/Restyled Vintage CORE for the two historical reference
# models. Each completed bundle is uploaded immediately so an interrupted or
# destroyed instance only has to repeat the active bundle.

set -euo pipefail

MODE="${1:-all}"
case "$MODE" in
    all|modern-d24|gpt1900-d34) ;;
    *)
        echo "Usage: bash runs/vintage-core-reference-models.sh {all|modern-d24|gpt1900-d34}" >&2
        exit 2
        ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

export NANOCHAT_BASE_DIR="${NANOCHAT_BASE_DIR:-/workspace/nanochat}"
export OMP_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

if [ -n "${NANOCHAT_PREBUILT_VENV:-}" ]; then
    # shellcheck disable=SC1091
    source "$NANOCHAT_PREBUILT_VENV/bin/activate"
elif [ -x /opt/think-nano-venv/bin/python ]; then
    # shellcheck disable=SC1091
    source /opt/think-nano-venv/bin/activate
elif [ -x .venv/bin/python ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
else
    echo "No think.nano Python environment found." >&2
    exit 2
fi

: "${HF_TOKEN:?HF_TOKEN must be set in the environment or .env}"
: "${WANDB_API_KEY:?WANDB_API_KEY must be set in the environment or .env}"

EVALUATOR_COMMIT="82b7e92adf04aac6418b29e6bbca7ddfd479c462"
EVALUATOR_ROOT="$NANOCHAT_BASE_DIR/vintage-core-evaluator-$EVALUATOR_COMMIT"
RESULTS_ROOT="$NANOCHAT_BASE_DIR/reference-evals/vintage-core-v1.0.0"
CACHE_ROOT="$NANOCHAT_BASE_DIR/reference-evals/cache"

if [ ! -e "$EVALUATOR_ROOT/.git" ]; then
    git fetch origin "$EVALUATOR_COMMIT"
    git worktree add --detach "$EVALUATOR_ROOT" "$EVALUATOR_COMMIT"
fi
test "$(git -C "$EVALUATOR_ROOT" rev-parse HEAD)" = "$EVALUATOR_COMMIT"

python -c 'import jinja2, torch, yaml, huggingface_hub, wandb; print("Vintage CORE dependencies PASS")'

MODE="$MODE" EVALUATOR_ROOT="$EVALUATOR_ROOT" RESULTS_ROOT="$RESULTS_ROOT" CACHE_ROOT="$CACHE_ROOT" python -u - <<'PY'
import hashlib
import io
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import wandb
from huggingface_hub import HfApi, hf_hub_download

mode = os.environ["MODE"]
evaluator_root = Path(os.environ["EVALUATOR_ROOT"])
evaluator_dir = evaluator_root / "dev" / "vintage_core_colab"
evaluator = evaluator_dir / "vintage_core_eval.py"
results_root = Path(os.environ["RESULTS_ROOT"])
cache_root = Path(os.environ["CACHE_ROOT"])
results_root.mkdir(parents=True, exist_ok=True)
cache_root.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(evaluator_dir))

import vintage_core_eval as vc

models = vc.read_json(evaluator_dir / "models.json")["models"]
expected = {
    "modern-d24": {
        "artifact_repo": "ChrisMcCormick/nanochat-d24-2026-02-02",
        "artifact_revision": "2ccf42323ff3bedcc986191d688e5827f33c237c",
        "runtime_revision": "7ac837cff8efc0e85502e2b3a934a35e2d937b8d",
    },
    "gpt1900-d34": {
        "artifact_repo": "mhla/gpt1900-d34-22btok",
        "artifact_revision": "d6330f9f0a17ce13da36fb951d7987bb03e6fbd0",
        "runtime_revision": None,
    },
}
selected_models = list(expected) if mode == "all" else [mode]
bundle_names = ["original", "filtered", "restyled"]
token = os.environ.get("HF_TOKEN")
result_repo = "jbduran/bart-experiments"
api = HfApi(token=token)
uploaded_hashes = set()

# Prove that this token can create the new result namespace before spending GPU time.
api.upload_file(
    repo_id=result_repo,
    repo_type="model",
    path_or_fileobj=io.BytesIO(json.dumps({
        "schema_version": 1,
        "evaluator_commit": "82b7e92adf04aac6418b29e6bbca7ddfd479c462",
        "models": selected_models,
        "bundles": bundle_names,
    }, indent=2).encode()),
    path_in_repo="evaluations/vintage-core-v1.0.0/_runner.json",
    commit_message="Initialize durable Vintage CORE result namespace",
)
print(f"Hugging Face persistence preflight PASS: {result_repo}", flush=True)


def assert_registry(model_id):
    entry = models[model_id]
    wanted = expected[model_id]
    if entry["artifact_repo"] != wanted["artifact_repo"]:
        raise SystemExit(f"Unexpected artifact repo for {model_id}")
    if entry["artifact_revision"] != wanted["artifact_revision"]:
        raise SystemExit(f"Unexpected artifact revision for {model_id}")
    runtime_revision = entry["runtime"].get("revision")
    if runtime_revision != wanted["runtime_revision"]:
        raise SystemExit(f"Unexpected runtime revision for {model_id}")


def restore_remote(model_id, output_dir):
    prefix = f"evaluations/vintage-core-v1.0.0/{model_id}"
    try:
        files = api.list_repo_files(result_repo, repo_type="model")
    except Exception as exc:
        print(f"Could not inspect prior remote results for {model_id}: {exc}", flush=True)
        return
    restored = 0
    for repo_path in files:
        if not repo_path.startswith(prefix + "/"):
            continue
        cached = hf_hub_download(
            result_repo, repo_path, repo_type="model", token=token,
            cache_dir=str(cache_root / "results"),
        )
        destination = output_dir / repo_path.removeprefix(prefix + "/")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cached, destination)
        restored += 1
    if restored:
        print(f"Restored {restored} persistent files for {model_id}", flush=True)


def upload_completed_json(model_id, output_dir):
    for bundle in bundle_names:
        path = output_dir / f"{bundle}.json"
        if not vc.completed_bundle_results(model_id, [bundle], output_dir, -1):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        marker = (model_id, bundle, digest)
        if marker in uploaded_hashes:
            continue
        try:
            api.upload_file(
                repo_id=result_repo,
                repo_type="model",
                path_or_fileobj=str(path),
                path_in_repo=f"evaluations/vintage-core-v1.0.0/{model_id}/{bundle}.json",
                commit_message=f"Save {model_id} {bundle} Vintage CORE result",
            )
        except Exception as exc:
            print(
                f"UPLOAD RETRY NEEDED for {model_id}/{bundle}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            continue
        uploaded_hashes.add(marker)
        print(f"PERSISTED IMMEDIATELY: {model_id}/{bundle}.json", flush=True)


def run_model(model_id, output_dir):
    upload_completed_json(model_id, output_dir)
    command = [
        sys.executable,
        "-u",
        str(evaluator),
        "--model",
        model_id,
        "--bundles",
        ",".join(bundle_names),
        "--output-dir",
        str(output_dir),
        "--cache-dir",
        str(cache_root),
        "--max-per-task",
        "-1",
    ]
    print("Running:", " ".join(command), flush=True)
    process = subprocess.Popen(
        command,
        cwd=str(evaluator_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    assert process.stdout is not None
    output_queue = queue.Queue()

    def pump_output():
        for line in process.stdout:
            output_queue.put(line)
        output_queue.put(None)

    threading.Thread(target=pump_output, daemon=True).start()
    started = time.monotonic()
    while True:
        try:
            line = output_queue.get(timeout=30)
        except queue.Empty:
            upload_completed_json(model_id, output_dir)
            completed = [
                bundle for bundle in bundle_names
                if vc.completed_bundle_results(model_id, [bundle], output_dir, -1)
            ]
            try:
                gpu_status = subprocess.check_output(
                    [
                        "nvidia-smi",
                        "--query-gpu=utilization.gpu,memory.used",
                        "--format=csv,noheader,nounits",
                    ],
                    text=True,
                    timeout=5,
                ).strip().replace("\n", "; ")
            except Exception as exc:
                gpu_status = f"unavailable ({type(exc).__name__})"
            elapsed = (time.monotonic() - started) / 60
            print(
                f"[heartbeat {model_id}: {elapsed:.1f} min | "
                f"GPU util%, memory MiB: {gpu_status} | "
                f"completed: {completed or 'none'}]",
                flush=True,
            )
            continue
        if line is None:
            break
        print(line, end="", flush=True)
        upload_completed_json(model_id, output_dir)
    returncode = process.wait()
    upload_completed_json(model_id, output_dir)
    if returncode:
        raise subprocess.CalledProcessError(returncode, command)


def log_wandb(model_id, output_dir):
    records = {
        name: vc.read_json(output_dir / f"{name}.json")
        for name in bundle_names
    }
    common = sorted(set.intersection(*(
        set(record["centered_results"]) for record in records.values()
    )))
    if len(common) != 20:
        raise SystemExit(f"{model_id}: expected a 20-task intersection, found {len(common)}")
    payload = {"eval/vintage_core/version": "v1.0.0"}
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
        f"think.nano:vintage-core-v1.0.0:{model_id}".encode()
    ).hexdigest()[:8]
    run = wandb.init(
        entity="jbduran-thinkingmachinesncsu",
        project="think.nano",
        id=run_id,
        resume="allow",
        name=f"vintage-core-{model_id}",
        group="vintage-core-reference-models",
        tags=["vintage-core", "reference-model", model_id],
    )
    run.log(payload)
    run.summary.update(payload)
    run.finish()
    print(f"Logged {model_id} to W&B run {run_id}", flush=True)


for model_id in selected_models:
    print(f"\n=== {model_id} ===", flush=True)
    assert_registry(model_id)
    output_dir = results_root / model_id
    output_dir.mkdir(parents=True, exist_ok=True)
    restore_remote(model_id, output_dir)
    run_model(model_id, output_dir)
    vc.write_tables(model_id, bundle_names, output_dir)
    log_wandb(model_id, output_dir)
    api.upload_folder(
        repo_id=result_repo,
        repo_type="model",
        folder_path=str(output_dir),
        path_in_repo=f"evaluations/vintage-core-v1.0.0/{model_id}",
        commit_message=f"Finalize {model_id} Vintage CORE tables",
    )
    print(f"Completed {model_id}: {output_dir}", flush=True)

print("All requested reference evaluations are complete.", flush=True)
PY
