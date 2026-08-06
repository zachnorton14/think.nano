#!/bin/bash

# Final single-H100 d32 run. Preparation, the faithful one-step memory smoke,
# training, and full BPB evaluation are deliberately separate commands.

set -euo pipefail

MODE="${1:-}"
case "$MODE" in
    preflight|prepare|smoke|train|eval|plan) ;;
    *)
        echo "Usage: bash runs/Think.Unbounded-d32.sh {preflight|prepare|smoke|train|eval|plan}" >&2
        exit 2
        ;;
esac

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

export OMP_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false
export NANOCHAT_BASE_DIR="${NANOCHAT_BASE_DIR:-/workspace/nanochat}"
export NANOCHAT_EXPERIMENT_ROOT="${NANOCHAT_EXPERIMENT_ROOT:-$NANOCHAT_BASE_DIR/experiments}"
export TORCHINDUCTOR_COMPILE_THREADS="${TORCHINDUCTOR_COMPILE_THREADS:-8}"
export TORCHINDUCTOR_CACHE_DIR="${TORCHINDUCTOR_CACHE_DIR:-$NANOCHAT_BASE_DIR/torchinductor-Think.Unbounded-d32}"

CONFIG="$REPO_ROOT/configs/base/Think.Unbounded-d32.json"
EXPERIMENT_ROOT="$NANOCHAT_EXPERIMENT_ROOT/Think.Unbounded-d32"
SMOKE_ROOT="$NANOCHAT_BASE_DIR/smoke/Think.Unbounded-d32-b2"
SMOKE_MARKER="$NANOCHAT_BASE_DIR/smoke/Think.Unbounded-d32-b2-passed.json"

mkdir -p "$NANOCHAT_BASE_DIR" "$TORCHINDUCTOR_CACHE_DIR"

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

if [ -n "${NANOCHAT_PREBUILT_VENV:-}" ]; then
    : "${NANOCHAT_PREBUILT_LOCK:?Prebuilt image must set NANOCHAT_PREBUILT_LOCK}"
    if [ ! -f "$NANOCHAT_PREBUILT_LOCK" ] || ! cmp -s uv.lock "$NANOCHAT_PREBUILT_LOCK"; then
        echo "Prebuilt image dependency lock does not match this checkout." >&2
        exit 2
    fi
    # shellcheck disable=SC1091
    source "$NANOCHAT_PREBUILT_VENV/bin/activate"
else
    command -v uv >/dev/null 2>&1 || {
        echo "No prebuilt environment or uv installation is available." >&2
        exit 2
    }
    [ -d .venv ] || uv venv
    uv sync --frozen --extra gpu
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

require_credentials() {
    : "${HF_TOKEN:?HF_TOKEN must be set in the environment or .env}"
    : "${WANDB_API_KEY:?WANDB_API_KEY must be set in the environment or .env}"
}

check_disk() {
    local minimum_gib="$1"
    MINIMUM_GIB="$minimum_gib" python - <<'PY'
import os
import shutil

base = os.environ["NANOCHAT_BASE_DIR"]
minimum_gib = int(os.environ["MINIMUM_GIB"])
free = shutil.disk_usage(base).free
print(f"Disk free under {base}: {free / 1024**3:.1f} GiB")
if free < minimum_gib * 1024**3:
    raise SystemExit(
        f"Need at least {minimum_gib} GiB free under {base}; "
        f"found {free / 1024**3:.1f} GiB"
    )
PY
}

run_gpu_preflight() {
    nvidia-smi -L
    python -m scripts.container_smoke
    python -u -m torch.distributed.run \
        --standalone \
        --nproc-per-node=1 \
        -m scripts.gpu_preflight \
        --expected-gpus 1
}

verify_caches() {
    CONFIG_PATH="$CONFIG" python - <<'PY'
import hashlib
import json
import math
import os
from pathlib import Path

from nanochat.mixture import MixtureSchedule
from scripts.experiment import Experiment
from scripts.pretok_think import _tokenizer_fingerprint

config_path = Path(os.environ["CONFIG_PATH"])
config = json.loads(config_path.read_text())
experiment = Experiment(config_path)
fingerprint = _tokenizer_fingerprint(str(experiment.tokenizer_dir))
if not fingerprint:
    raise SystemExit(f"Tokenizer is missing or empty: {experiment.tokenizer_dir}")

training = config["training"]
schedule = MixtureSchedule.from_config(
    config["mixture_schedule"],
    total_batch_size=int(training["total_batch_size"]),
)
planned = schedule.planned_tokens_per_source(start_tokens=0)
slack = float(config["pretokenize"]["slack"])
required_val = int(config["pretokenize"]["val_tokens"])
source_unique = {}

for source, output_dir in experiment.mixture_source_dirs.items():
    meta_path = output_dir / "meta.json"
    if not meta_path.is_file():
        raise SystemExit(f"Missing cache metadata for {source}: {meta_path}")
    meta = json.loads(meta_path.read_text())
    required_train = math.ceil(planned[source] * slack)
    actual_train = int(meta.get("train_tokens", 0))
    actual_val = int(meta.get("val_tokens", 0))
    dataset = config["datasets"][source]
    expected_repo = dataset["repo"]
    if dataset.get("subfolder"):
        expected_repo += "/" + dataset["subfolder"].strip("/")
    checks = {
        "dtype": meta.get("dtype") == "uint16",
        "tokenizer": meta.get("tokenizer_fingerprint") == fingerprint,
        "source": meta.get("source_dataset_repo") == expected_repo,
        "revision": meta.get("source_revision") == dataset["revision"],
        "train_tokens": actual_train >= required_train,
        "val_tokens": actual_val >= required_val,
        "not_exhausted": not meta.get("train_source_exhausted", False),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise SystemExit(
            f"Cache verification failed for {source}: {', '.join(failed)}; "
            f"train={actual_train:,}/{required_train:,}, "
            f"val={actual_val:,}/{required_val:,}"
        )
    for split in ("train", "val"):
        for entry in meta.get(f"{split}_files", []):
            path = output_dir / entry["filename"]
            if not path.is_file() or path.stat().st_size == 0:
                raise SystemExit(f"Missing or empty {source} cache file: {path}")
    source_unique[source] = actual_train
    print(
        f"Cache PASS {source}: {actual_train:,} train tokens, "
        f"{actual_val:,} val tokens"
    )

schedule.check_epoch_cap(source_unique, start_tokens=0)
print("All d32 token caches passed size, source, revision, tokenizer, and epoch checks.")
print(f"Config SHA256: {hashlib.sha256(config_path.read_bytes()).hexdigest()}")
PY
}

verify_smoke_marker() {
    CONFIG_PATH="$CONFIG" SMOKE_MARKER_PATH="$SMOKE_MARKER" python - <<'PY'
import hashlib
import json
import os
import subprocess
from pathlib import Path

config = Path(os.environ["CONFIG_PATH"])
marker_path = Path(os.environ["SMOKE_MARKER_PATH"])
if not marker_path.is_file():
    raise SystemExit(f"Missing batch-2 smoke marker: {marker_path}")
marker = json.loads(marker_path.read_text())
expected = {
    "git_commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip(),
    "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
    "device_batch_size": 2,
}
for key, value in expected.items():
    if marker.get(key) != value:
        raise SystemExit(
            f"Stale smoke marker: {key}={marker.get(key)!r}, expected {value!r}. "
            "Run the smoke mode again."
        )
print(
    f"Batch-2 smoke marker PASS: peak_memory_mib={marker['peak_memory_mib']:.1f}"
)
PY
}

cleanup_smoke_root() {
    SMOKE_ROOT_PATH="$SMOKE_ROOT" python - <<'PY'
import os
import shutil
from pathlib import Path

path = Path(os.environ["SMOKE_ROOT_PATH"]).resolve()
base = (Path(os.environ["NANOCHAT_BASE_DIR"]) / "smoke").resolve()
if path.parent != base or path.name != "Think.Unbounded-d32-b2":
    raise SystemExit(f"Refusing to clean unexpected smoke path: {path}")
shutil.rmtree(path, ignore_errors=True)
print(f"Removed temporary smoke checkpoint: {path}")
PY
}

case "$MODE" in
    preflight)
        check_disk "${MIN_FREE_GIB:-250}"
        run_gpu_preflight
        ;;
    prepare)
        require_credentials
        check_disk "${MIN_FREE_GIB:-250}"
        run_gpu_preflight
        python -u -m scripts.experiment prepare --config "$CONFIG" --nproc-per-node 1
        verify_caches
        python -u -m scripts.experiment plan --config "$CONFIG" --nproc-per-node 1
        ;;
    smoke)
        check_disk "${MIN_FREE_GIB:-60}"
        run_gpu_preflight
        SMOKE_TOKENIZER_DIR="${SMOKE_TOKENIZER_DIR:-$EXPERIMENT_ROOT/tokenizer}"
        SMOKE_PRETOKENIZED_DIR="${SMOKE_PRETOKENIZED_DIR:-$EXPERIMENT_ROOT/pretok_original}"
        if [ ! -f "$SMOKE_TOKENIZER_DIR/tokenizer.pkl" ]; then
            echo "Missing smoke tokenizer: $SMOKE_TOKENIZER_DIR/tokenizer.pkl" >&2
            exit 2
        fi
        if [ ! -f "$SMOKE_PRETOKENIZED_DIR/meta.json" ]; then
            echo "Missing smoke token cache: $SMOKE_PRETOKENIZED_DIR/meta.json" >&2
            exit 2
        fi
        mkdir -p "$(dirname "$SMOKE_ROOT")"
        SMOKE_LOG="$NANOCHAT_BASE_DIR/smoke/Think.Unbounded-d32-b2.log"
        trap cleanup_smoke_root EXIT
        python -u -m scripts.base_train \
            --depth=32 \
            --seed=42 \
            --model-tag=Think.Unbounded-d32-memory-smoke \
            --experiment-id=Think.Unbounded-d32-memory-smoke \
            --checkpoint-dir="$SMOKE_ROOT" \
            --tokenizer-dir="$SMOKE_TOKENIZER_DIR" \
            --window-pattern=SSSL \
            --max-seq-len=4096 \
            --device-batch-size=2 \
            --total-batch-size=8192 \
            --num-iterations=1 \
            --target-param-data-ratio=12 \
            --muon-momentum=0.9 \
            --fp8 \
            --fp8-recipe=tensorwise \
            --eval-every=-1 \
            --core-metric-every=-1 \
            --sample-every=-1 \
            --save-every=-1 \
            --run=dummy \
            --pretokenized \
            --pretokenized-dir="$SMOKE_PRETOKENIZED_DIR" \
            2>&1 | tee "$SMOKE_LOG"
        CONFIG_PATH="$CONFIG" SMOKE_LOG_PATH="$SMOKE_LOG" SMOKE_MARKER_PATH="$SMOKE_MARKER" python - <<'PY'
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

config = Path(os.environ["CONFIG_PATH"])
log_path = Path(os.environ["SMOKE_LOG_PATH"])
matches = re.findall(r"Peak memory usage: ([0-9.]+)MiB", log_path.read_text())
if not matches:
    raise SystemExit(f"Smoke completed without a peak-memory record: {log_path}")
peak = float(matches[-1])
if peak >= 76 * 1024:
    raise SystemExit(f"Batch 2 leaves insufficient H100 headroom: {peak:.1f} MiB")
marker = {
    "git_commit": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True
    ).strip(),
    "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
    "device_batch_size": 2,
    "peak_memory_mib": peak,
}
marker_path = Path(os.environ["SMOKE_MARKER_PATH"])
marker_path.parent.mkdir(parents=True, exist_ok=True)
marker_path.write_text(json.dumps(marker, indent=2) + "\n")
print(f"Batch-2 d32 memory smoke PASS: {peak:.1f} MiB peak")
PY
        cleanup_smoke_root
        trap - EXIT
        ;;
    train)
        require_credentials
        check_disk "${MIN_FREE_GIB:-80}"
        run_gpu_preflight
        verify_caches
        verify_smoke_marker
        python -u -m scripts.experiment plan --config "$CONFIG" --nproc-per-node 1
        python -u -m scripts.experiment train --config "$CONFIG" --nproc-per-node 1
        ;;
    eval)
        require_credentials
        check_disk "${MIN_FREE_GIB:-40}"
        python -u -m scripts.experiment eval \
            --config "$CONFIG" \
            --nproc-per-node 1 \
            --per-position-bpb-only
        ;;
    plan)
        python -u -m scripts.experiment plan --config "$CONFIG" --nproc-per-node 1
        ;;
esac
