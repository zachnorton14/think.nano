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
import json
import os
import shutil
import sys
from pathlib import Path

import wandb
from huggingface_hub import HfApi, hf_hub_download, snapshot_download

mode = os.environ["MODE"]
evaluator_root = Path(os.environ["EVALUATOR_ROOT"])
evaluator_dir = evaluator_root / "dev" / "vintage_core_colab"
results_root = Path(os.environ["RESULTS_ROOT"])
cache_root = Path(os.environ["CACHE_ROOT"])
results_root.mkdir(parents=True, exist_ok=True)
cache_root.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(evaluator_dir))

import vintage_core_eval as vc

models = vc.read_json(evaluator_dir / "models.json")["models"]
bundle_registry = vc.read_json(evaluator_dir / "bundles.json")["bundles"]
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
result_repo = "jbduran/think.nano"
api = HfApi(token=token)


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


def upload_results(model_id, output_dir, message):
    api.upload_folder(
        repo_id=result_repo,
        repo_type="model",
        folder_path=str(output_dir),
        path_in_repo=f"evaluations/vintage-core-v1.0.0/{model_id}",
        commit_message=message,
    )
    print(f"Persisted {model_id}: {message}", flush=True)


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
    entry = models[model_id]
    snapshot = vc.download_model(entry, cache_root, token)
    runtime = vc.resolve_runtime(entry, snapshot, cache_root)

    for bundle_name in bundle_names:
        if vc.completed_bundle_results(model_id, [bundle_name], output_dir, -1):
            print(f"Keeping completed persistent bundle: {model_id}/{bundle_name}", flush=True)
            continue
        bundles = vc.resolve_bundles(
            [bundle_name], bundle_registry, cache_root, token
        )
        vc.run_worker(
            model_id, entry, snapshot, runtime, bundles, output_dir, -1
        )
        if not vc.completed_bundle_results(model_id, [bundle_name], output_dir, -1):
            raise SystemExit(f"{model_id}/{bundle_name} did not produce a valid result")
        upload_results(
            model_id, output_dir,
            f"Save {model_id} {bundle_name} Vintage CORE result",
        )

    vc.write_tables(model_id, bundle_names, output_dir)
    log_wandb(model_id, output_dir)
    upload_results(model_id, output_dir, f"Finalize {model_id} Vintage CORE tables")
    print(f"Completed {model_id}: {output_dir}", flush=True)

print("All requested reference evaluations are complete.", flush=True)
PY
