#!/bin/bash

# One resumable Vast.ai pipeline:
#   1. Think.Unbounded d32 C3 robust v3 SFT across both GPUs
#   2. Karpathy d34 base -> complete modern SFT across both GPUs
#   3. Pinned 120-row IFEval-mini evaluation of four models

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

export NANOCHAT_BASE_DIR="${NANOCHAT_BASE_DIR:-/workspace/nanochat}"
export NANOCHAT_EXPERIMENT_ROOT="${NANOCHAT_EXPERIMENT_ROOT:-$NANOCHAT_BASE_DIR/experiments}"
export HF_HOME="${HF_HOME:-$NANOCHAT_BASE_DIR/huggingface}"

python -m pip install --quiet "absl-py>=2.3.1" "immutabledict>=4.2.1" "langdetect>=1.0.9" "nltk>=3.9.1"
NANOCHAT_NLTK_DIR="${NANOCHAT_NLTK_DIR:-$HOME/nltk_data}"
install -d -m 700 "$NANOCHAT_NLTK_DIR"
python -m nltk.downloader -d "$NANOCHAT_NLTK_DIR" punkt punkt_tab
export NLTK_DATA="$NANOCHAT_NLTK_DIR"

export NPROC_PER_NODE="${NPROC_PER_NODE:-2}"

echo "=== Training 1/2: C3Rv3 across both GPUs ==="
DEFER_CHATCORE=1 \
    bash runs/Think.Unbounded-d32-v2mix-cont-pre1930-c3-robust-v3-sft.sh

echo "=== Training 2/2: D34 modern SFT across both GPUs ==="
bash runs/karpathy-nanochat-d34-complete-modern-sft.sh

echo "=== Both dual-GPU training jobs completed successfully ==="

echo "=== Evaluating 4 models on pinned IFEval-mini-120 ==="
python -u -m scripts.run_ifeval_suite \
    --config configs/ifeval/four-models-mini120-v1.json
