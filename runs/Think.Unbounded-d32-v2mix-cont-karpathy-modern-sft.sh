#!/bin/bash

# Karpathy discussion #8 SFT on Think.Unbounded d32, followed by a full
# historical ChatCORE comparison against the vintage C3 robust v2 SFT.

set -euo pipefail

MODE="${1:-all}"
case "$MODE" in
    all|train|eval) ;;
    *) echo "Usage: bash $0 {all|train|eval}" >&2; exit 2 ;;
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
    echo "No think.nano prebuilt Python environment found." >&2
    exit 2
fi

: "${HF_TOKEN:?HF_TOKEN must be set in .env or the environment}"
: "${WANDB_API_KEY:?WANDB_API_KEY must be set in .env or the environment}"

export NANOCHAT_BASE_DIR="${NANOCHAT_BASE_DIR:-/workspace/nanochat}"
export NANOCHAT_EXPERIMENT_ROOT="${NANOCHAT_EXPERIMENT_ROOT:-$NANOCHAT_BASE_DIR/experiments}"

PARENT_EXPERIMENT_ID="Think.Unbounded-d32-v2mix-cont"
PARENT_STEP=9600
BASE_CONFIG="configs/base/Think.Unbounded-d32-v2mix-cont.json"
MODERN_CONFIG="configs/sft/Think.Unbounded-d32-v2mix-cont-karpathy-modern-sft-v1.json"
VINTAGE_CONFIG="configs/sft/pre1930-curriculum-c3-robust-v2.json"

BASE_CONFIG="$BASE_CONFIG" MODERN_CONFIG="$MODERN_CONFIG" PARENT_STEP="$PARENT_STEP" python - <<'PY'
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
training = modern["training"]

if base.get("experiment_id") != "Think.Unbounded-d32-v2mix-cont":
    raise SystemExit("Wrong d32 parent config")
if _config_iterations(base) != step:
    raise SystemExit(f"D32 parent final step is not exactly {step}")
if modern.get("experiment_suffix") != "karpathy-modern-sft-v1":
    raise SystemExit("Modern SFT must use a distinct experiment suffix")
if modern.get("data", {}).get("recipe") != "karpathy-discussion8":
    raise SystemExit("Modern SFT is not using the historical Karpathy mixture")
expected = {
    "num_epochs": 1,
    "target_examples_per_step": 32,
    "device_batch_size": 2,
    "load_optimizer": 0,
    "init_lr_frac": 0.02,
    "warmup_ratio": 0.0,
    "warmdown_ratio": 1.0,
    "final_lr_frac": 0.0,
}
for key, value in expected.items():
    if training.get(key) != value:
        raise SystemExit(f"Modern SFT {key}={training.get(key)!r}, expected {value!r}")
if not torch.cuda.is_available():
    raise SystemExit("PyTorch cannot access CUDA")
print(
    f"Runtime PASS: python={sys.executable}, torch={torch.__version__}, "
    f"wandb={wandb.__version__}, gpu={torch.cuda.get_device_name(0)}"
)
print("Karpathy recipe PASS: 1 epoch, 32 examples/step, 2% LR with linear decay")
PY

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
    echo "Running full Karpathy-suite eval for vintage C3 robust v2 SFT..."
    python -u -m scripts.experiment eval \
        --config "$VINTAGE_CONFIG" \
        --parent-experiment-id "$PARENT_EXPERIMENT_ID" \
        --parent-step "$PARENT_STEP" \
        --core-only \
        --chat-suite karpathy \
        --full-chatcore \
        --chat-batch-size 8

    echo "Running full Karpathy-suite eval for modern SFT..."
    python -u -m scripts.experiment eval \
        --config "$MODERN_CONFIG" \
        --parent-experiment-id "$PARENT_EXPERIMENT_ID" \
        --parent-step "$PARENT_STEP" \
        --core-only \
        --chat-suite karpathy \
        --full-chatcore \
        --chat-batch-size 8

    echo "Both full comparison evals were synced to Hugging Face."
fi
