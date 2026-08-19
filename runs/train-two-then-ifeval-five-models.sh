#!/bin/bash

# One resumable Vast.ai pipeline:
#   1. Start C3Rv3 on GPU 0 and D34 modern SFT on GPU 1 concurrently
#   2. Whenever either 80 GB GPU frees up, claim the next one-GPU IFEval job
#   3. Score/upload four models on the pinned 120-row IFEval-mini subset

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

if ! python -m pip --version >/dev/null 2>&1; then
    python -m ensurepip --upgrade
fi
python -m pip install --quiet "absl-py>=2.3.1" "immutabledict>=4.2.1" "langdetect>=1.0.9" "nltk>=3.9.1"
NANOCHAT_NLTK_DIR="${NANOCHAT_NLTK_DIR:-$HOME/nltk_data}"
install -d -m 700 "$NANOCHAT_NLTK_DIR"
python -m nltk.downloader -d "$NANOCHAT_NLTK_DIR" punkt punkt_tab
export NLTK_DATA="$NANOCHAT_NLTK_DIR"

python -u -m scripts.run_train_eval_queue
