#!/bin/bash

# clean1930s-d24-r12-ctx4096-sssl-fulltok-mix-og
#
# Branches clean1930s-d24-r12-ctx4096-sssl-fulltok-v1 at step 6000 (~70% of its 8352-step
# horizon) and trains the remaining 2352 steps on the 0/30/60 midtrain mixture:
#
#     base       steps [    0, 5846)  original       <- the parent's, never re-run
#     injection  steps [ 5846, 7516)  midtrain_r30   <- active from step 6000
#     decay_mix  steps [ 7516, 8352)  midtrain_r60
#
# The parent is read-only. Its step-6000 weights and all four optimizer shards are copied
# into this experiment's own tree; nothing is ever written back to the v1 run.
#
# Default: 4x fully NVLink-connected H100 SXM. The parent's optimizer state is sharded per
# rank and its shard shapes are a function of the world size that wrote them, so a branch
# that inherits it is pinned to 4 GPUs. See the NPROC_PER_NODE guard below.
#
# Safe to re-run: every step is idempotent. An interrupted run picks up from its own last
# complete checkpoint, an adequate token cache is reused rather than rebuilt, and the
# branch point stays pinned in run.json.
#
# On Vast, artifacts default to /workspace/nanochat. Otherwise they use the standard
# ~/.cache/nanochat location. Keep roughly 250 GiB free.
#
# Run as:
#   bash runs/clean1930s-d24-r12-ctx4096-sssl-fulltok-mix-og.sh

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

# The 'original' mixture source is the same dataset, tokenizer and cache the parent trained
# on, so the hosted v1 cache is reused verbatim instead of being re-tokenized. The branch
# never draws from it (it starts inside the injection stage) but it still backs the
# headline val/bpb, which keeps this run's loss curve comparable to v1's.
export PRETOKENIZED_REPO="${PRETOKENIZED_REPO:-jbduran/clean1930s-d24-r12-ctx4096-fulltok-v1-pretok}"
export HOSTED_PRETOKENIZED_DIR="${HOSTED_PRETOKENIZED_DIR:-$NANOCHAT_BASE_DIR/hosted_pretok/clean1930s-fulltok-v1}"

# Optional: pre-built token caches for the midtrain sources, as {"source": "hf/repo"}.
# Anything not listed here is downloaded as parquet and tokenized locally (~2.6B tokens
# across r30 + r60, which is hours of CPU work -- host them if you will rerun this).
export HOSTED_PRETOK_REPOS="${HOSTED_PRETOK_REPOS:-}"

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

# A branch that inherits optimizer state must run at the parent's world size: each rank
# loads optim_006000_rank<rank>.pt, and the AdamW slice heights and Muon chunk widths were
# both computed from world_size=4. Fail here rather than after the first torch.compile.
if [ "$NPROC_PER_NODE" != "4" ]; then
    echo "NPROC_PER_NODE must be 4: clean1930s-d24-r12-ctx4096-sssl-fulltok-v1 wrote its" >&2
    echo "optimizer shards from a 4-rank run and they cannot be reshaped. To run at a" >&2
    echo 'different width, set "load_optimizer": false in the config branch block first' >&2
    echo "(that discards the parent's Muon momentum and AdamW moments)." >&2
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

# Fetch the branch parent, restore the tokenizer, point the 'original' source at the cache
# the parent trained on, and build the two midtrain caches. prepare_dataset skips the
# parquet download for any source whose cache already covers its planned draw, so
# 'original' costs nothing here beyond the snapshot below.
python - <<'PY'
import json
import os
from pathlib import Path

from huggingface_hub import snapshot_download

from scripts.experiment import Experiment

experiment = Experiment(
    os.environ["BASE_CONFIG_PATH"],
    nproc_per_node=int(os.environ["NPROC_PER_NODE"]),
)
experiment.initialize()

# Resolve and copy the parent's weights plus all four optimizer shards into this
# experiment's own tree. Raises with the exact missing filenames if the parent has not
# uploaded a complete step 6000 yet. The v1 run is only ever read from.
step = experiment.prepare_branch_parent()
experiment.print_branch_table()
print(f"Branching from {experiment.branch_parent_id} at step {step}", flush=True)

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

# Optional pre-built caches for the midtrain sources.
hosted = json.loads(os.environ.get("HOSTED_PRETOK_REPOS") or "{}")
for source, repo_id in hosted.items():
    if source not in experiment.mixture_source_dirs:
        raise SystemExit(
            f"HOSTED_PRETOK_REPOS names {source!r}, which is not a mixture source "
            f"({sorted(experiment.mixture_source_dirs)})"
        )
    target = experiment.mixture_source_dirs[source]
    target.mkdir(parents=True, exist_ok=True)
    print(f"Restoring hosted token cache for {source!r} from {repo_id}", flush=True)
    snapshot_download(
        repo_id=repo_id,
        repo_type="dataset",
        revision="main",
        local_dir=str(target),
        token=os.environ["HF_TOKEN"],
    )

experiment.prepare_dataset()
experiment.prepare_pretokenized()
PY

# Read-only summary: the branch table (parent beside this run, every changed value marked)
# and the mixture stage boundaries in tokens and steps, with the epoch cap checked against
# the caches just prepared. Worth reading before committing the GPU hours.
python -u -m scripts.experiment plan --config "$BASE_CONFIG_PATH"

python -u -m scripts.experiment train \
    --config "$BASE_CONFIG_PATH" \
    --nproc-per-node "$NPROC_PER_NODE"
