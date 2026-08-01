#!/bin/bash

# Branch clean1930s-d24-r12-ctx4096-sssl-fulltok-v1 at step 6000 and train the last 30%
# of its schedule on the 0/30/60 midtrain mixture.
#
# The parent is never modified: its weights and optimizer shards are copied into a new
# experiment tree (clean1930s-d24-r12-ctx4096-sssl-fulltok-mix-og) and everything after
# that is written under the new experiment id.
#
# Default: 4x fully NVLink-connected H100 SXM. The parent's optimizer state is sharded
# per rank, so branching with load_optimizer=true REQUIRES the same world size the parent
# ran at. Set NPROC_PER_NODE to anything else and prepare will refuse.
#
# On Vast, artifacts default to /workspace/nanochat. Otherwise they use the standard
# ~/.cache/nanochat location. Keep roughly 250 GiB free.

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
export BASE_CONFIG_PATH="${BASE_CONFIG_PATH:-$REPO_ROOT/configs/base/clean1930s-d24-r12-ctx4096-sssl-fulltok-mix-og.json}"
# The 'original' source is the same dataset, tokenizer and cache the parent trained on,
# so the hosted v1 cache is reused verbatim rather than re-tokenized.
export PRETOKENIZED_REPO="${PRETOKENIZED_REPO:-jbduran/clean1930s-d24-r12-ctx4096-fulltok-v1-pretok}"
export HOSTED_PRETOKENIZED_DIR="${HOSTED_PRETOKENIZED_DIR:-$NANOCHAT_BASE_DIR/hosted_pretok/clean1930s-fulltok-v1}"
export NPROC_PER_NODE="${NPROC_PER_NODE:-4}"
export MIN_FREE_GIB="${MIN_FREE_GIB:-250}"
export REQUIRE_FULL_NVLINK="${REQUIRE_FULL_NVLINK:-1}"
export TORCHINDUCTOR_COMPILE_THREADS="${TORCHINDUCTOR_COMPILE_THREADS:-1}"
export TORCHINDUCTOR_CACHE_DIR="${TORCHINDUCTOR_CACHE_DIR:-$NANOCHAT_BASE_DIR/torchinductor-d24-ctx4096-sssl}"
mkdir -p "$NANOCHAT_BASE_DIR"
mkdir -p "$TORCHINDUCTOR_CACHE_DIR"
mkdir -p "$HOSTED_PRETOKENIZED_DIR"

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

: "${HF_TOKEN:?HF_TOKEN must be set in the environment or .env}"
: "${WANDB_API_KEY:?WANDB_API_KEY must be set in the environment or .env}"

# A branch that inherits optimizer state is pinned to the parent's world size: each rank
# loads optim_<step>_rank<rank>.pt, and the AdamW/Muon shard shapes are functions of the
# world size that wrote them. Fail here rather than after the first compile.
if [ "$NPROC_PER_NODE" != "4" ]; then
    echo "NPROC_PER_NODE must be 4: the parent's optimizer shards were written by a" >&2
    echo "4-rank run and cannot be reshaped. To run at a different width, set" >&2
    echo '"load_optimizer": false in the config branch block first.' >&2
    exit 2
fi

# A compatible Vast image carries the exact uv.lock and a ready virtualenv.
# Ordinary instances retain the original speedrun-style setup path.
if [ -n "${NANOCHAT_PREBUILT_VENV:-}" ]; then
    : "${NANOCHAT_PREBUILT_LOCK:?Prebuilt image must set NANOCHAT_PREBUILT_LOCK}"
    if [ ! -f "$NANOCHAT_PREBUILT_LOCK" ] || ! cmp -s uv.lock "$NANOCHAT_PREBUILT_LOCK"; then
        echo "Prebuilt image dependency lock does not match this checkout." >&2
        echo "Use the image tag built for the current uv.lock; refusing a stale environment." >&2
        exit 2
    fi
    if [ ! -f "$NANOCHAT_PREBUILT_VENV/bin/activate" ]; then
        echo "Prebuilt virtualenv is missing: $NANOCHAT_PREBUILT_VENV" >&2
        exit 2
    fi
    # shellcheck disable=SC1091
    source "$NANOCHAT_PREBUILT_VENV/bin/activate"
    echo "Using prebuilt environment matching uv.lock."
else
    command -v uv &> /dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
    [ -d .venv ] || uv venv
    uv sync --frozen --extra gpu
    source .venv/bin/activate
fi

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

# Fail before downloading anything if the CUDA runtime, Hopper FP8/FA3 kernels, full
# NVLink topology, or cross-GPU NCCL communication are not working.
echo "GPU topology:"
nvidia-smi topo -m
PREFLIGHT_ARGS=(--expected-gpus "$NPROC_PER_NODE")
if [ "$REQUIRE_FULL_NVLINK" = "1" ]; then
    PREFLIGHT_ARGS+=(--require-full-nvlink)
elif [ "$REQUIRE_FULL_NVLINK" != "0" ]; then
    echo "REQUIRE_FULL_NVLINK must be 0 or 1 (got $REQUIRE_FULL_NVLINK)." >&2
    exit 2
fi
python -u -m torch.distributed.run \
    --standalone \
    --nproc-per-node="$NPROC_PER_NODE" \
    -m scripts.gpu_preflight \
    "${PREFLIGHT_ARGS[@]}"

# Fetch the parent checkpoint, point the 'original' mixture source at the hosted cache the
# parent trained on, and build the two midtrain caches. prepare_dataset skips the parquet
# download for any source whose cache already covers its planned draw, so 'original' costs
# nothing here beyond the snapshot below.
python - <<'PY'
import os
from pathlib import Path

from huggingface_hub import snapshot_download

from scripts.experiment import Experiment

experiment = Experiment(
    os.environ["BASE_CONFIG_PATH"],
    nproc_per_node=int(os.environ["NPROC_PER_NODE"]),
)
experiment.initialize()

# Resolve and copy the parent weights + all four optimizer shards into this experiment's
# own tree. The parent run is only read from; nothing is written back to it.
step = experiment.prepare_branch_parent()
experiment.print_branch_table()
print(f"Branching from {experiment.branch_parent_id} at step {step}")

experiment.prepare_tokenizer()

# All compatible experiments share one physical copy of the 18 GB hosted cache.
# Preserve an older non-empty experiment-local cache if one already exists.
shared_dir = Path(os.environ["HOSTED_PRETOKENIZED_DIR"]).resolve()
local_dir = experiment.mixture_source_dirs["original"]
local_dir.parent.mkdir(parents=True, exist_ok=True)
if local_dir.is_symlink():
    if local_dir.resolve() != shared_dir:
        raise RuntimeError(
            f"Pretok symlink {local_dir} points to {local_dir.resolve()}, not {shared_dir}"
        )
elif local_dir.exists() and any(local_dir.iterdir()):
    shared_dir = local_dir
else:
    if local_dir.exists():
        local_dir.rmdir()
    local_dir.symlink_to(shared_dir, target_is_directory=True)

snapshot_download(
    repo_id=os.environ["PRETOKENIZED_REPO"],
    repo_type="dataset",
    revision="main",
    local_dir=str(shared_dir),
    token=os.environ["HF_TOKEN"],
)

experiment.prepare_dataset()
experiment.prepare_pretokenized()
PY

python -u -m scripts.experiment train \
    --config "$BASE_CONFIG_PATH" \
    --nproc-per-node "$NPROC_PER_NODE"
