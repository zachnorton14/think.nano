#!/bin/bash

# On two 80 GB GPUs, import Karpathy's clean d34 base checkpoint and SFT it on the complete,
# uncapped nanochat-default mixture. This is deliberately a separate legacy
# architecture lane; weights are never converted to the current GPT.

set -euo pipefail

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
    echo "No think.nano Python environment found." >&2
    exit 2
fi

: "${HF_TOKEN:?HF_TOKEN must be set in .env or the environment}"
: "${WANDB_API_KEY:?WANDB_API_KEY must be set in .env or the environment}"

NPROC_PER_NODE="${NPROC_PER_NODE:-2}"
export NPROC_PER_NODE

python - <<'PY'
import os
import sys

try:
    import torch
    import wandb
except ImportError as exc:
    raise SystemExit(f"Prebuilt environment dependency missing: {exc}") from exc

if not torch.cuda.is_available():
    raise SystemExit("PyTorch cannot access CUDA in the selected prebuilt environment")
required = int(os.environ["NPROC_PER_NODE"])
visible = torch.cuda.device_count()
if visible < required:
    raise SystemExit(
        f"SFT requires {required} visible CUDA device(s); found {visible}. "
        "Clear any single-GPU CUDA_VISIBLE_DEVICES setting."
    )
minimum_bytes = 70 * 1024**3
gpu_specs = []
for index in range(required):
    props = torch.cuda.get_device_properties(index)
    if props.total_memory < minimum_bytes:
        raise SystemExit(
            f"GPU {index} has {props.total_memory / 1024**3:.1f} GiB; "
            f"this launcher requires {required} 80 GB-class GPU(s)"
        )
    gpu_specs.append(
        f"{torch.cuda.get_device_name(index)} {props.total_memory / 1024**3:.1f}GiB"
    )
print(
    f"Runtime PASS: python={sys.executable}, torch={torch.__version__}, "
    f"wandb={wandb.__version__}, training_gpus={required} "
    f"({', '.join(gpu_specs)})"
)
PY

export NANOCHAT_BASE_DIR="${NANOCHAT_BASE_DIR:-/workspace/nanochat}"
export NANOCHAT_EXPERIMENT_ROOT="${NANOCHAT_EXPERIMENT_ROOT:-$NANOCHAT_BASE_DIR/experiments}"
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"
export NANOCHAT_DIST_OPTIMIZER_LOW_MEMORY="${NANOCHAT_DIST_OPTIMIZER_LOW_MEMORY:-0}"

PARENT_ID="karpathy-nanochat-d34"
PARENT_STEP=169150
SFT_CONFIG="configs/sft/karpathy-nanochat-d34-complete-modern-sft-v5-parallel-2xa100-80gb.json"

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
print("Identity dataset PASS: 1,000 rows (presented twice by nanochat-default)")
PY

python -u -m scripts.import_flat_nanochat_model \
    --repo-id karpathy/nanochat-d34 \
    --revision c48357d43863a3a6cdc5f5db5b4ec5964e4192d6 \
    --experiment-id "$PARENT_ID" \
    --step "$PARENT_STEP" \
    --architecture nanochat_legacy_2025

python -u -m scripts.experiment prepare \
    --config "$SFT_CONFIG" \
    --parent-experiment-id "$PARENT_ID" \
    --parent-step "$PARENT_STEP" \
    --nproc-per-node "$NPROC_PER_NODE"

python -u -m scripts.experiment train \
    --config "$SFT_CONFIG" \
    --parent-experiment-id "$PARENT_ID" \
    --parent-step "$PARENT_STEP" \
    --nproc-per-node "$NPROC_PER_NODE" \
    --defer-chatcore
