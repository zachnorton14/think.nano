#!/bin/bash

# Data-matched modern Nanochat SFT on Think.Unbounded d32. The modern mixture is
# deterministically capped to the Vintage C3Rv2 schedule's 652,950 row presentations.

set -euo pipefail

MODE="${1:-all}"
case "$MODE" in
    all|train|eval) ;;
    *) echo "Usage: bash $0 {all|train|eval}" >&2; exit 2 ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if pgrep -af 'python.*-m scripts[.]chat_eval' >/dev/null; then
    echo "Another full chat evaluation is still running. Wait for it to finish, then rerun this command." >&2
    pgrep -af 'python.*-m scripts[.]chat_eval' >&2 || true
    exit 2
fi

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
    echo "No think.nano prebuilt Python environment found." >&2
    exit 2
fi

: "${HF_TOKEN:?HF_TOKEN must be set in .env or the environment}"
: "${WANDB_API_KEY:?WANDB_API_KEY must be set in .env or the environment}"

export NANOCHAT_BASE_DIR="${NANOCHAT_BASE_DIR:-/workspace/nanochat}"
export NANOCHAT_EXPERIMENT_ROOT="${NANOCHAT_EXPERIMENT_ROOT:-$NANOCHAT_BASE_DIR/experiments}"

PARENT_EXPERIMENT_ID="Think.Unbounded-d32-v2mix-cont"
PARENT_STEP=9600
MATCHED_PRESENTATIONS=652950
BASE_CONFIG="configs/base/Think.Unbounded-d32-v2mix-cont.json"
MODERN_CONFIG="configs/sft/Think.Unbounded-d32-v2mix-cont-nanochat-default-datamatch-v1.json"
VINTAGE_CONFIG="configs/sft/pre1930-curriculum-c3-robust-v2.json"

BASE_CONFIG="$BASE_CONFIG" MODERN_CONFIG="$MODERN_CONFIG" \
PARENT_STEP="$PARENT_STEP" MATCHED_PRESENTATIONS="$MATCHED_PRESENTATIONS" python - <<'PY'
import json
import os
import sys
from pathlib import Path

import torch
import wandb
from scripts.experiment import _config_iterations

base = json.loads(Path(os.environ["BASE_CONFIG"]).read_text())
modern = json.loads(Path(os.environ["MODERN_CONFIG"]).read_text())
step = int(os.environ["PARENT_STEP"])
target = int(os.environ["MATCHED_PRESENTATIONS"])
data = modern.get("data", {})
training = modern.get("training", {})

if base.get("experiment_id") != "Think.Unbounded-d32-v2mix-cont":
    raise SystemExit("Wrong d32 parent config")
if _config_iterations(base) != step:
    raise SystemExit(f"D32 parent final step is not exactly {step}")
if modern.get("experiment_suffix") != "nanochat-default-datamatch-v1":
    raise SystemExit("Wrong matched-modern experiment suffix")
if data.get("recipe") != "nanochat-default":
    raise SystemExit("Matched modern SFT must execute nanochat-default")
if data.get("max_train_presentations") != target:
    raise SystemExit(f"Modern presentation cap must be exactly {target:,}")
expected = {
    "num_iterations": -1,
    "device_batch_size": 2,
    "load_optimizer": 0,
    "init_lr_frac": 0.8,
    "warmup_ratio": 0.03,
    "warmdown_ratio": 0.5,
    "final_lr_frac": 0.0,
}
for key, value in expected.items():
    if training.get(key) != value:
        raise SystemExit(f"Matched modern {key}={training.get(key)!r}, expected {value!r}")
if not torch.cuda.is_available():
    raise SystemExit("PyTorch cannot access CUDA")
print(
    f"Runtime PASS: python={sys.executable}, torch={torch.__version__}, "
    f"wandb={wandb.__version__}, gpu={torch.cuda.get_device_name(0)}"
)
print(f"Data-match PASS: exactly {target:,} deterministic modern row presentations")
print("Control PASS: packed 4096-token path, fresh optimizer, and Vintage LR schedule")
PY

# Fail before loading the model if a public source was renamed or gated.
python - <<'PY'
import os
import time

from huggingface_hub import HfApi
from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError

datasets = (
    "HuggingFaceTB/smol-smoltalk",
    "cais/mmlu",
    "openai/gsm8k",
    "allenai/ai2_arc",
    "openai/openai_humaneval",
)
api = HfApi(token=os.environ.get("HF_TOKEN"))
for repo_id in datasets:
    for attempt in range(4):
        try:
            api.repo_info(repo_id, repo_type="dataset")
            print(f"Public dataset PASS: {repo_id}")
            break
        except (GatedRepoError, RepositoryNotFoundError) as exc:
            raise SystemExit(f"Required public dataset is unavailable: {repo_id}: {exc}") from exc
        except Exception as exc:
            if attempt == 3:
                raise SystemExit(
                    f"Could not verify required dataset after retries: {repo_id}: {exc}"
                ) from exc
            time.sleep(2 ** attempt)
PY

IDENTITY_FILE="$NANOCHAT_BASE_DIR/identity_conversations.jsonl"
if [ ! -s "$IDENTITY_FILE" ]; then
    mkdir -p "$NANOCHAT_BASE_DIR"
    curl -fL --retry 4 --retry-all-errors \
        -o "$IDENTITY_FILE.tmp" \
        https://karpathy-public.s3.us-west-2.amazonaws.com/identity_conversations.jsonl
    mv "$IDENTITY_FILE.tmp" "$IDENTITY_FILE"
fi
IDENTITY_FILE="$IDENTITY_FILE" python - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["IDENTITY_FILE"])
rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
if len(rows) != 1_000:
    raise SystemExit(f"Identity dataset has {len(rows):,} rows; expected exactly 1,000")
if not all(isinstance(row, list) and len(row) >= 2 for row in rows):
    raise SystemExit("Identity dataset contains an invalid conversation")
print("Identity dataset PASS: 1,000 rows (presented twice by the modern recipe)")
PY

full_eval_complete() {
    local config_path="$1"
    EVAL_CONFIG="$config_path" PARENT_EXPERIMENT_ID="$PARENT_EXPERIMENT_ID" \
    PARENT_STEP="$PARENT_STEP" python - <<'PY'
import json
import os
from pathlib import Path

from huggingface_hub import hf_hub_download
from scripts.experiment import Experiment, _copy_cached_file

expected_tasks = {"ARC-Easy", "ARC-Challenge", "MMLU", "GSM8K", "HumanEval"}
experiment = Experiment(
    os.environ["EVAL_CONFIG"],
    parent_experiment_id=os.environ["PARENT_EXPERIMENT_ID"],
    parent_step=int(os.environ["PARENT_STEP"]),
    nproc_per_node=1,
)
experiment.validate_config()
remote_steps = experiment.complete_remote_steps(strict=True)
if not remote_steps:
    raise SystemExit(1)
final_step = remote_steps[-1]
local_path = experiment.eval_dir / "chatcore.json"

def valid(path):
    try:
        payload = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return False
    suite = payload.get("chatcore_suite", {})
    results = payload.get("results", {})
    return (
        payload.get("step") == final_step
        and payload.get("complete", True) is True
        and suite.get("name") == "karpathy"
        and suite.get("max_generative_problems") is None
        and suite.get("generative_answer_format") is None
        and set(suite.get("tasks", [])) == expected_tasks
        and set(results) == expected_tasks
        and all(isinstance(value, (int, float)) for value in results.values())
        and isinstance(payload.get("chatcore_metric"), (int, float))
    )

if valid(local_path):
    print(f"Full eval complete locally: {experiment.experiment_id} step {final_step}")
    raise SystemExit(0)

remote_path = experiment.remote_path("evals/chatcore.json")
remote_files = experiment.remote_files(strict=True, path_in_repo=experiment.remote_path("evals"))
if remote_path in remote_files:
    cached = hf_hub_download(
        experiment.hf_repo, remote_path, repo_type="model", token=os.environ.get("HF_TOKEN")
    )
    local_path.parent.mkdir(parents=True, exist_ok=True)
    _copy_cached_file(cached, local_path)
    if valid(local_path):
        print(f"Full eval complete on Hugging Face: {experiment.experiment_id} step {final_step}")
        raise SystemExit(0)
raise SystemExit(1)
PY
}

if [ "$MODE" = "all" ] || [ "$MODE" = "train" ]; then
    python -u -m scripts.experiment prepare \
        --config "$MODERN_CONFIG" \
        --parent-experiment-id "$PARENT_EXPERIMENT_ID" \
        --parent-step "$PARENT_STEP"

    python -u -m scripts.experiment train \
        --config "$MODERN_CONFIG" \
        --parent-experiment-id "$PARENT_EXPERIMENT_ID" \
        --parent-step "$PARENT_STEP" \
        --defer-chatcore
fi

if [ "$MODE" = "all" ] || [ "$MODE" = "eval" ]; then
    if full_eval_complete "$MODERN_CONFIG"; then
        echo "Skipping matched-modern eval: exact full result already exists."
    else
        echo "Running full Karpathy-suite eval for the data-matched modern SFT..."
        python -u -m scripts.experiment eval \
            --config "$MODERN_CONFIG" \
            --parent-experiment-id "$PARENT_EXPERIMENT_ID" \
            --parent-step "$PARENT_STEP" \
            --core-only \
            --chat-suite karpathy \
            --full-chatcore \
            --chat-batch-size 8
        full_eval_complete "$MODERN_CONFIG"
    fi

    if ! full_eval_complete "$VINTAGE_CONFIG"; then
        echo "Vintage full eval is missing. Finish the existing paired-eval launcher first." >&2
        exit 2
    fi

    MODERN_CONFIG="$MODERN_CONFIG" VINTAGE_CONFIG="$VINTAGE_CONFIG" \
    PARENT_EXPERIMENT_ID="$PARENT_EXPERIMENT_ID" PARENT_STEP="$PARENT_STEP" python - <<'PY'
import json
import os
import time

from scripts.experiment import Experiment, atomic_json

def load(config):
    experiment = Experiment(
        config,
        parent_experiment_id=os.environ["PARENT_EXPERIMENT_ID"],
        parent_step=int(os.environ["PARENT_STEP"]),
        nproc_per_node=1,
    )
    return experiment, json.loads((experiment.eval_dir / "chatcore.json").read_text())

vintage, vintage_eval = load(os.environ["VINTAGE_CONFIG"])
modern, modern_eval = load(os.environ["MODERN_CONFIG"])
if vintage_eval["chatcore_suite"] != modern_eval["chatcore_suite"]:
    raise SystemExit("Refusing comparison: evaluation suite metadata differs")
tasks = vintage_eval["chatcore_suite"]["tasks"]
comparison = {
    "schema_version": 1,
    "generated_at": int(time.time()),
    "base_experiment_id": os.environ["PARENT_EXPERIMENT_ID"],
    "parent_step": int(os.environ["PARENT_STEP"]),
    "matching": {
        "priority": "row_presentations",
        "target_presentations": 652950,
        "reference_stage_training_flops": 1.0107782648656036e18,
    },
    "suite": vintage_eval["chatcore_suite"],
    "vintage": {
        "experiment_id": vintage.experiment_id,
        "step": vintage_eval["step"],
        "chatcore_metric": vintage_eval["chatcore_metric"],
        "results": vintage_eval["results"],
    },
    "modern_data_matched": {
        "experiment_id": modern.experiment_id,
        "step": modern_eval["step"],
        "chatcore_metric": modern_eval["chatcore_metric"],
        "results": modern_eval["results"],
    },
    "modern_minus_vintage": {
        "chatcore_metric": modern_eval["chatcore_metric"] - vintage_eval["chatcore_metric"],
        "results": {
            task: modern_eval["results"][task] - vintage_eval["results"][task]
            for task in tasks
        },
    },
}
output = modern.eval_dir / "vintage_vs_modern_datamatch.json"
atomic_json(output, comparison)
modern.upload_file(
    output,
    "evals/vintage_vs_modern_datamatch.json",
    "Upload data-matched Vintage versus modern SFT comparison",
)
print(json.dumps(comparison, indent=2))
print(f"Uploaded comparison to {modern.remote_path('evals/vintage_vs_modern_datamatch.json')}")
PY
fi

echo "Data-matched modern SFT workflow complete."
