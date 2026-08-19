#!/bin/bash

# One resumable Vast.ai pipeline:
#   1. Think.Unbounded d32 C3 robust v3 SFT
#   2. Karpathy d34 base -> complete modern SFT
#   3. Official 541-row IFEval on the requested five models

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
python -m nltk.downloader -d "$NANOCHAT_BASE_DIR/nltk_data" punkt punkt_tab
export NLTK_DATA="$NANOCHAT_BASE_DIR/nltk_data"

echo "=== Training 1/2: Think.Unbounded d32 C3 robust v3 ==="
DEFER_CHATCORE=1 bash runs/Think.Unbounded-d32-v2mix-cont-pre1930-c3-robust-v3-sft.sh

echo "=== Training 2/2: Karpathy d34 complete modern SFT ==="
bash runs/karpathy-nanochat-d34-complete-modern-sft.sh

echo "=== Evaluating 5/5 models on official 541-row IFEval ==="
python -u -m scripts.run_ifeval_suite \
    --config configs/ifeval/five-models-v1.json
