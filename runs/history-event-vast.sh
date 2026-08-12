#!/bin/bash

# Durable single-GPU HISTORY-EVENT BPB evaluation. One model is resident at a
# time; partial append-only results are synchronized to the dataset repository.

set -euo pipefail

MODE="${1:-all}"
case "$MODE" in
    all|think-unbounded-d32-step9600|gpt1900-d34|llama-3.1-8b-instruct) ;;
    *)
        echo "Usage: bash runs/history-event-vast.sh {all|think-unbounded-d32-step9600|gpt1900-d34|llama-3.1-8b-instruct}" >&2
        exit 2
        ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

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
    echo "No locked think.nano Python environment found." >&2
    exit 2
fi

: "${HF_TOKEN:?HF_TOKEN must be set in .env or the environment}"

export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1
export HISTORY_EVENT_DATASET_REPO="${HISTORY_EVENT_DATASET_REPO:-jbduran/history-event-reconstruction}"
export HISTORY_EVENT_RESULTS_ROOT="${HISTORY_EVENT_RESULTS_ROOT:-/workspace/history-event-results}"
export HISTORY_EVENT_CACHE_ROOT="${HISTORY_EVENT_CACHE_ROOT:-/workspace/history-event-cache}"
export HISTORY_EVENT_EVALUATOR_COMMIT="$(git rev-parse HEAD)"
export MODE

python - <<'PY'
import os
import shutil
from pathlib import Path

import torch
from huggingface_hub import HfApi, hf_hub_download

from dev.history_event.models import MODEL_SPECS

if not torch.cuda.is_available():
    raise SystemExit("CUDA preflight failed")
properties = torch.cuda.get_device_properties(0)
if properties.total_memory < 75 * 1024**3:
    raise SystemExit(f"80 GB GPU required; found {properties.total_memory / 1024**3:.1f} GiB")
if not torch.cuda.is_bf16_supported():
    raise SystemExit("GPU does not support bf16")
free_disk = shutil.disk_usage(Path(os.environ["HISTORY_EVENT_RESULTS_ROOT"]).parent).free
if free_disk < 200 * 1024**3:
    raise SystemExit(f"At least 200 GiB free disk required; found {free_disk / 1024**3:.1f} GiB")

api = HfApi(token=os.environ["HF_TOKEN"])
identity = api.whoami()
api.dataset_info(os.environ["HISTORY_EVENT_DATASET_REPO"])
for model_id, spec in MODEL_SPECS.items():
    info = api.model_info(spec["repo_id"], revision=spec["revision"])
    if info.sha != spec["revision"]:
        raise SystemExit(f"{model_id}: expected {spec['revision']}, resolved {info.sha}")
events = hf_hub_download(
    os.environ["HISTORY_EVENT_DATASET_REPO"], "events/test.jsonl",
    repo_type="dataset", token=os.environ["HF_TOKEN"],
    cache_dir=str(Path(os.environ["HISTORY_EVENT_CACHE_ROOT"]) / "dataset"),
)
Path(os.environ["HISTORY_EVENT_RESULTS_ROOT"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["HISTORY_EVENT_RESULTS_ROOT"], "events-path.txt").write_text(events + "\n")
print(f"Preflight PASS: {identity.get('name', 'authenticated user')}; {properties.name}; {properties.total_memory / 1024**3:.1f} GiB")
PY

python -u - <<'PY'
import hashlib
import io
import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download

from dev.history_event.chart import MODEL_ORDER

mode = os.environ["MODE"]
repo_id = os.environ["HISTORY_EVENT_DATASET_REPO"]
results_root = Path(os.environ["HISTORY_EVENT_RESULTS_ROOT"])
cache_root = Path(os.environ["HISTORY_EVENT_CACHE_ROOT"])
events_path = Path((results_root / "events-path.txt").read_text().strip())
api = HfApi(token=os.environ["HF_TOKEN"])
prefix_root = "results/history-event-bpb-v1"
models = MODEL_ORDER if mode == "all" else [mode]
uploaded = {}

runner_manifest = {
    "schema_version": 1,
    "evaluator_commit": os.environ["HISTORY_EVENT_EVALUATOR_COMMIT"],
    "models": models,
    "dtype": "bfloat16",
    "quantization": None,
    "chat_template": False,
}
api.upload_file(
    repo_id=repo_id, repo_type="dataset",
    path_or_fileobj=io.BytesIO(json.dumps(runner_manifest, indent=2).encode()),
    path_in_repo=f"{prefix_root}/_runner.json",
    commit_message="Initialize HISTORY-EVENT BPB runner",
)


def restore(model_id, output_dir):
    remote_prefix = f"{prefix_root}/{model_id}/"
    for repo_path in api.list_repo_files(repo_id, repo_type="dataset"):
        if not repo_path.startswith(remote_prefix):
            continue
        cached = hf_hub_download(
            repo_id, repo_path, repo_type="dataset", token=os.environ["HF_TOKEN"],
            cache_dir=str(cache_root / "results"),
        )
        destination = output_dir / repo_path.removeprefix(remote_prefix)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cached, destination)


def upload_changed(model_id, output_dir):
    if not output_dir.exists():
        return
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        key = (model_id, str(path.relative_to(output_dir)))
        if uploaded.get(key) == digest:
            continue
        api.upload_file(
            repo_id=repo_id, repo_type="dataset", path_or_fileobj=str(path),
            path_in_repo=f"{prefix_root}/{model_id}/{path.relative_to(output_dir)}",
            commit_message=f"Checkpoint {model_id} HISTORY-EVENT BPB",
        )
        uploaded[key] = digest
        print(f"Persisted {model_id}/{path.relative_to(output_dir)}", flush=True)


def run_monitored(model_id, output_dir, limit=None):
    command = [
        "python", "-u", "-m", "dev.history_event", "score",
        "--model", model_id,
        "--events", str(events_path),
        "--output-dir", str(output_dir),
        "--cache-dir", str(cache_root),
    ]
    if limit is not None:
        command.extend(["--limit", str(limit)])
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    assert process.stdout is not None
    lines = queue.Queue()

    def pump():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    while True:
        try:
            line = lines.get(timeout=30)
        except queue.Empty:
            upload_changed(model_id, output_dir)
            continue
        if line is None:
            break
        print(line, end="", flush=True)
        upload_changed(model_id, output_dir)
    returncode = process.wait()
    upload_changed(model_id, output_dir)
    if returncode:
        raise subprocess.CalledProcessError(returncode, command)


for model_id in models:
    output_dir = results_root / model_id
    output_dir.mkdir(parents=True, exist_ok=True)
    restore(model_id, output_dir)
    print(f"=== Loading/scoring one-event preflight: {model_id} ===", flush=True)
    run_monitored(model_id, output_dir, limit=1)
    print(f"=== Full score: {model_id} ===", flush=True)
    run_monitored(model_id, output_dir)
    summary = json.loads((output_dir / "summary.json").read_text())
    if not summary.get("complete") or summary.get("unresolved_errors"):
        raise SystemExit(f"Incomplete {model_id}: {summary}")

if mode == "all":
    chart_dir = results_root / "chart"
    subprocess.run([
        "python", "-m", "dev.history_event", "chart",
        "--results-root", str(results_root),
        "--output-dir", str(chart_dir),
    ], check=True)
    api.upload_folder(
        repo_id=repo_id, repo_type="dataset", folder_path=str(chart_dir),
        path_in_repo=f"{prefix_root}/chart",
        commit_message="Publish HISTORY-EVENT surprisingness chart",
    )
print("Requested HISTORY-EVENT runs are complete.", flush=True)
PY
