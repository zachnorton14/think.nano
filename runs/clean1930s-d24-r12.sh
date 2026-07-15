#!/bin/bash

# Train clean1930s d24 at r12 and 4096 context from the hosted tokenizer/cache.
# Default: 8x H100. Override with NPROC_PER_NODE=4 for a 4x H100 node.
# On Vast, artifacts default to /workspace/nanochat. Otherwise they use the
# standard ~/.cache/nanochat location. Keep roughly 200 GiB free.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

export OMP_NUM_THREADS=1
if [ -d /workspace ]; then
    DEFAULT_NANOCHAT_BASE_DIR=/workspace/nanochat
else
    DEFAULT_NANOCHAT_BASE_DIR="$HOME/.cache/nanochat"
fi
export NANOCHAT_BASE_DIR="${NANOCHAT_BASE_DIR:-$DEFAULT_NANOCHAT_BASE_DIR}"
export BASE_CONFIG_PATH="${BASE_CONFIG_PATH:-$REPO_ROOT/configs/base/clean1930s-d24-r12-ctx4096-fulltok-v1.json}"
export PRETOKENIZED_REPO="${PRETOKENIZED_REPO:-jbduran/clean1930s-d24-r12-ctx4096-fulltok-v1-pretok}"
export NPROC_PER_NODE="${NPROC_PER_NODE:-8}"
export MIN_FREE_GIB="${MIN_FREE_GIB:-200}"
mkdir -p "$NANOCHAT_BASE_DIR"

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

: "${HF_TOKEN:?HF_TOKEN must be set in the environment or .env}"
: "${WANDB_API_KEY:?WANDB_API_KEY must be set in the environment or .env}"

case "$NPROC_PER_NODE" in
    4|8) ;;
    *)
        echo "NPROC_PER_NODE must be 4 or 8 (got $NPROC_PER_NODE)." >&2
        exit 2
        ;;
esac

# Match runs/speedrun.sh environment setup.
command -v uv &> /dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
[ -d .venv ] || uv venv
uv sync --extra gpu
source .venv/bin/activate

python - <<'PY'
import os
import shutil

base_dir = os.environ["NANOCHAT_BASE_DIR"]
minimum = int(os.environ["MIN_FREE_GIB"]) * 1024**3
available = shutil.disk_usage(base_dir).free
if available < minimum:
    raise SystemExit(
        f"Need at least {minimum / 1024**3:.0f} GiB free under {base_dir}; "
        f"found {available / 1024**3:.1f} GiB. Set NANOCHAT_BASE_DIR to a larger "
        "persistent volume, or intentionally lower MIN_FREE_GIB."
    )
print(f"Storage preflight passed: {available / 1024**3:.1f} GiB free in {base_dir}")
PY

# Fail before downloading the hosted token cache if the CUDA runtime, Hopper
# FP8/FA3 kernels, or cross-GPU NCCL communication are not working. PCIe-only
# H100 nodes are supported; nvidia-smi topology is printed for diagnostics.
echo "GPU topology:"
nvidia-smi topo -m
python -u -m torch.distributed.run \
    --standalone \
    --nproc-per-node="$NPROC_PER_NODE" \
    -m scripts.gpu_preflight \
    --expected-gpus "$NPROC_PER_NODE"

# Restore the already-trained public tokenizer and private uint16 token cache.
# prepare_pretokenized validates and reuses this cache; it does not download parquet
# shards or tokenize text when the hosted cache is complete and compatible.
python - <<'PY'
import os

from huggingface_hub import snapshot_download

from scripts.experiment import Experiment

experiment = Experiment(os.environ["BASE_CONFIG_PATH"])
experiment.initialize()
experiment.prepare_tokenizer()
snapshot_download(
    repo_id=os.environ["PRETOKENIZED_REPO"],
    repo_type="dataset",
    revision="main",
    local_dir=str(experiment.pretok_dir),
    token=os.environ["HF_TOKEN"],
)
experiment.prepare_pretokenized()
PY

python -u -m scripts.experiment train \
    --config "$BASE_CONFIG_PATH" \
    --nproc-per-node "$NPROC_PER_NODE"
