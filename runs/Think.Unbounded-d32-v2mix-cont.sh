#!/bin/bash

# Data-repair continuation for Think.Unbounded-d32. The corrected v2 mixtures can be
# downloaded and pretokenized while the parent is still training. The GPU handoff is
# then a checkpoint branch at step 5500 with weights, optimizer, LR schedule, and the
# original-data cursor preserved.

set -euo pipefail

MODE="${1:-}"
case "$MODE" in
    preflight|prepare-data|prepare-parent|train|eval|plan) ;;
    *)
        echo "Usage: bash runs/Think.Unbounded-d32-v2mix-cont.sh {preflight|prepare-data|prepare-parent|train|eval|plan}" >&2
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

CONFIG="$REPO_ROOT/configs/base/Think.Unbounded-d32-v2mix-cont.json"
PARENT_ROOT="$NANOCHAT_EXPERIMENT_ROOT/Think.Unbounded-d32"
EXPERIMENT_ROOT="$NANOCHAT_EXPERIMENT_ROOT/Think.Unbounded-d32-v2mix-cont"
PARENT_SMOKE_MARKER="$NANOCHAT_BASE_DIR/smoke/Think.Unbounded-d32-b2-passed.json"

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

seed_parent_reuse() {
    local parent_tokenizer="$PARENT_ROOT/tokenizer"
    local parent_original="$PARENT_ROOT/pretok_original"
    local child_tokenizer="$EXPERIMENT_ROOT/tokenizer"
    local child_original="$EXPERIMENT_ROOT/pretok_original"

    [ -s "$parent_tokenizer/tokenizer.pkl" ] || {
        echo "Missing parent tokenizer: $parent_tokenizer/tokenizer.pkl" >&2
        exit 2
    }
    [ -s "$parent_original/meta.json" ] || {
        echo "Missing parent original cache: $parent_original/meta.json" >&2
        exit 2
    }

    mkdir -p "$EXPERIMENT_ROOT"
    if [ ! -e "$child_tokenizer" ]; then
        cp -a "$parent_tokenizer" "$child_tokenizer"
        echo "Copied the parent tokenizer into the continuation experiment."
    elif ! diff -qr "$parent_tokenizer" "$child_tokenizer" >/dev/null; then
        echo "Continuation tokenizer differs from the parent tokenizer: $child_tokenizer" >&2
        exit 2
    fi

    if [ -L "$child_original" ]; then
        if [ "$(readlink -f "$child_original")" != "$(readlink -f "$parent_original")" ]; then
            echo "Continuation original-cache link points at the wrong directory: $child_original" >&2
            exit 2
        fi
    elif [ -e "$child_original" ]; then
        echo "Refusing a copied/rebuilt original cache at $child_original; the restored cursor requires the exact parent cache." >&2
        exit 2
    else
        ln -s "$parent_original" "$child_original"
        echo "Linked the exact parent original cache into the continuation experiment."
    fi
}

verify_dataset_manifests() {
    CONFIG_PATH="$CONFIG" python - <<'PY'
import json
import math
import os
from pathlib import Path

from huggingface_hub import hf_hub_download
from nanochat.mixture import MixtureSchedule
from scripts.experiment import Experiment
from scripts.pretok_think import _tokenizer_fingerprint

config = json.loads(Path(os.environ["CONFIG_PATH"]).read_text())
experiment = Experiment(os.environ["CONFIG_PATH"], nproc_per_node=1)
fingerprint = _tokenizer_fingerprint(str(experiment.tokenizer_dir))
if not fingerprint:
    raise SystemExit("The seeded continuation tokenizer is missing or empty.")

schedule = MixtureSchedule.from_config(
    config["mixture_schedule"],
    total_batch_size=int(config["training"]["total_batch_size"]),
)
draws = schedule.planned_tokens_per_source(start_tokens=0)
expected_ratios = {"midtrain_r21": 0.21, "midtrain_r45": 0.45}
old_ranges = {}
consumed_midtrain = 0.0

for source, target_ratio in expected_ratios.items():
    dataset = config["datasets"][source]
    prefix = dataset["subfolder"].rsplit("/data", 1)[0]
    cached = hf_hub_download(
        repo_id=dataset["repo"], repo_type="dataset",
        filename=f"{prefix}/manifest.json", revision=dataset["revision"],
        token=os.environ.get("HF_TOKEN"),
    )
    manifest = json.loads(Path(cached).read_text())
    achieved = float(manifest["achieved"]["midtrain_pct_consumed_prefix"])
    if abs(achieved - 100 * target_ratio) > 0.1 + 1e-9:
        raise SystemExit(f"{source} ratio {achieved:.4f}% is outside the 0.1 pp tolerance")
    if int(manifest["tokens"]["consumed_prefix_tokens"]) != draws[source]:
        raise SystemExit(f"{source} consumed-prefix length does not match the d32 schedule")
    required = math.ceil(draws[source] * float(config["pretokenize"]["slack"]))
    if int(manifest["tokens"]["train_total"]) < required:
        raise SystemExit(
            f"{source} is too short for slack={config['pretokenize']['slack']}: "
            f"{manifest['tokens']['train_total']:,} < {required:,}"
        )
    if int(manifest["tokens"]["validation_total"]) < int(config["training"]["eval_tokens"]):
        raise SystemExit(f"{source} validation shard is too short")
    layout = manifest["layout"]
    if int(layout["n_train_shards"]) != int(dataset["num_train_shards"]):
        raise SystemExit(f"{source} train-shard count does not match the config")
    if int(layout["validation_shard_index"]) != int(dataset["validation_shard"]):
        raise SystemExit(f"{source} validation-shard index does not match the config")
    if manifest["tokenizer"]["fingerprint_sha256"] != fingerprint:
        raise SystemExit(f"{source} was measured with a different tokenizer")
    dedup = manifest["dedup"]
    zero_fields = (
        "written_pretraining_repeated_ids",
        "written_pretraining_duplicate_hashes",
        "written_cross_source_hash_overlap",
        "written_train_validation_id_overlap",
        "written_train_validation_hash_overlap",
    )
    failed = {key: dedup.get(key) for key in zero_fields if dedup.get(key) != 0}
    if failed:
        raise SystemExit(f"{source} dedup/overlap checks failed: {failed}")
    used = set(manifest["sources"]["old_corpus_shards_used"])
    if any(index <= 329 or index == 472 for index in used):
        raise SystemExit(f"{source} overlaps base-train or validation shards")
    old_ranges[source] = used
    consumed_midtrain += draws[source] * achieved / 100.0
    if manifest.get("generator", {}).get("code_commit") is None:
        print(f"WARNING {source}: manifest has no generator code commit; immutable data revision is still pinned.")
    print(
        f"Manifest PASS {source}: {achieved:.4f}% midtrain, "
        f"{manifest['tokens']['train_total']:,} train tokens, "
        f"{len(used)} unique old-corpus shards"
    )

if old_ranges["midtrain_r21"] & old_ranges["midtrain_r45"]:
    raise SystemExit("The r21 and r45 pretraining shard ranges overlap")
midtrain_pool_tokens = 608_471_853
epochs = consumed_midtrain / midtrain_pool_tokens
if epochs > 3.0:
    raise SystemExit(f"Combined midtrain consumption is {epochs:.4f} epochs > 3.0")
print(f"Combined consumed midtrain: {consumed_midtrain:,.0f} tokens = {epochs:.4f} pool epochs")
PY
}

verify_caches() {
    CONFIG_PATH="$CONFIG" python - <<'PY'
import json
import math
import os
from pathlib import Path

from nanochat.mixture import MixtureSchedule
from scripts.experiment import Experiment
from scripts.pretok_think import _tokenizer_fingerprint

config = json.loads(Path(os.environ["CONFIG_PATH"]).read_text())
experiment = Experiment(os.environ["CONFIG_PATH"], nproc_per_node=1)
fingerprint = _tokenizer_fingerprint(str(experiment.tokenizer_dir))
schedule = MixtureSchedule.from_config(
    config["mixture_schedule"],
    total_batch_size=int(config["training"]["total_batch_size"]),
)
start_tokens = experiment.mixture_start_tokens
planned = schedule.planned_tokens_per_source(start_tokens=start_tokens)
slack = float(config["pretokenize"]["slack"])
required_val = int(config["training"]["eval_tokens"])
source_unique = {}

for source, output_dir in experiment.active_mixture_source_dirs.items():
    meta_path = output_dir / "meta.json"
    if not meta_path.is_file():
        raise SystemExit(f"Missing cache metadata for {source}: {meta_path}")
    meta = json.loads(meta_path.read_text())
    required_train = math.ceil(planned[source] * slack)
    dataset = config["datasets"][source]
    expected_repo = dataset["repo"]
    if dataset.get("subfolder"):
        expected_repo += "/" + dataset["subfolder"].strip("/")
    checks = {
        "dtype": meta.get("dtype") == "uint16",
        "tokenizer": meta.get("tokenizer_fingerprint") == fingerprint,
        "source": meta.get("source_dataset_repo") == expected_repo,
        "revision": meta.get("source_revision") == dataset["revision"],
        "train_tokens": int(meta.get("train_tokens", 0)) >= required_train,
        "val_tokens": int(meta.get("val_tokens", 0)) >= required_val,
        "not_exhausted": not meta.get("train_source_exhausted", False),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise SystemExit(f"Cache verification failed for {source}: {', '.join(failed)}")
    for split in ("train", "val"):
        for entry in meta.get(f"{split}_files", []):
            path = output_dir / entry["filename"]
            expected_bytes = int(entry["num_tokens"]) * 2
            if not path.is_file() or path.stat().st_size != expected_bytes:
                raise SystemExit(f"Bad {source} cache file: {path}")
    source_unique[source] = int(meta["train_tokens"])
    print(
        f"Cache PASS {source}: {meta['train_tokens']:,} train tokens, "
        f"{meta['val_tokens']:,} val tokens"
    )

schedule.check_epoch_cap(source_unique, start_tokens=start_tokens)
print(f"All continuation caches pass from inherited step {experiment.branch['parent_step']:,}.")
PY
}

verify_parent_smoke() {
    SMOKE_MARKER_PATH="$PARENT_SMOKE_MARKER" python - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["SMOKE_MARKER_PATH"])
if not path.is_file():
    raise SystemExit(f"Missing parent batch-2 smoke marker: {path}")
marker = json.loads(path.read_text())
if marker.get("device_batch_size") != 2:
    raise SystemExit(f"Parent smoke used device_batch_size={marker.get('device_batch_size')}, expected 2")
peak = float(marker.get("peak_memory_mib", float("inf")))
if peak >= 76 * 1024:
    raise SystemExit(f"Parent batch-2 smoke has insufficient headroom: {peak:.1f} MiB")
print(f"Parent batch-2 smoke evidence PASS: peak_memory_mib={peak:.1f}")
PY
}

prepare_data_without_parent_checkpoint() {
    CONFIG_PATH="$CONFIG" python -u - <<'PY'
import os

from scripts.experiment import Experiment

experiment = Experiment(os.environ["CONFIG_PATH"], nproc_per_node=1)
experiment.initialize()
experiment.prepare_dataset()
# The exact parent tokenizer was copied before initialization. Do not call
# prepare_tokenizer(): its recovery path would rewrite experiment_tokenizer.json and
# change the fingerprint required by the reused original cache.
experiment.upload_folder(
    experiment.tokenizer_dir,
    "tokenizer",
    f"Reuse exact parent tokenizer for {experiment.experiment_id}",
)
experiment.prepare_pretokenized()
PY
}

case "$MODE" in
    preflight)
        check_disk "${MIN_FREE_GIB:-80}"
        run_gpu_preflight
        ;;
    prepare-data)
        require_credentials
        check_disk "${MIN_FREE_GIB:-60}"
        seed_parent_reuse
        verify_dataset_manifests
        prepare_data_without_parent_checkpoint
        verify_caches
        python -u -m scripts.experiment plan --config "$CONFIG" --nproc-per-node 1
        ;;
    prepare-parent)
        require_credentials
        seed_parent_reuse
        CONFIG_PATH="$CONFIG" python -u - <<'PY'
import os
from scripts.experiment import Experiment

experiment = Experiment(os.environ["CONFIG_PATH"], nproc_per_node=1)
experiment.initialize()
step = experiment.prepare_branch_parent()
experiment.print_branch_table()
print(f"Parent checkpoint PASS: step {step}")
PY
        ;;
    train)
        require_credentials
        check_disk "${MIN_FREE_GIB:-80}"
        seed_parent_reuse
        run_gpu_preflight
        verify_dataset_manifests
        verify_caches
        verify_parent_smoke
        python -u -m scripts.experiment plan --config "$CONFIG" --nproc-per-node 1
        python -u -m scripts.experiment train --config "$CONFIG" --nproc-per-node 1
        ;;
    eval)
        require_credentials
        seed_parent_reuse
        python -u -m scripts.experiment eval \
            --config "$CONFIG" \
            --nproc-per-node 1 \
            --per-position-bpb-only
        ;;
    plan)
        python -u -m scripts.experiment plan --config "$CONFIG" --nproc-per-node 1
        ;;
esac
