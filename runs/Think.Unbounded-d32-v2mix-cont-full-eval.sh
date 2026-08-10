#!/bin/bash

# Final evaluation for Think.Unbounded-d32-v2mix-cont: full original-validation
# BPB plus full Original, Filtered, and Restyled Vintage CORE.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

export NANOCHAT_BASE_DIR="${NANOCHAT_BASE_DIR:-/workspace/nanochat}"
export NANOCHAT_EXPERIMENT_ROOT="${NANOCHAT_EXPERIMENT_ROOT:-$NANOCHAT_BASE_DIR/experiments}"
export OMP_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false

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

: "${HF_TOKEN:?HF_TOKEN must be set in the environment or .env}"
: "${WANDB_API_KEY:?WANDB_API_KEY must be set in the environment or .env}"

EXPERIMENT_ID="Think.Unbounded-d32-v2mix-cont"
EXPERIMENT_ROOT="$NANOCHAT_EXPERIMENT_ROOT/$EXPERIMENT_ID"
CHECKPOINT_DIR="$EXPERIMENT_ROOT/base_checkpoints"
TOKENIZER_DIR="$EXPERIMENT_ROOT/tokenizer"
OUTPUT_DIR="$EXPERIMENT_ROOT/evals/vintage_core"
VINTAGE_ROOT="$NANOCHAT_BASE_DIR/vintage-core-v1.0.0"
CONFIG="configs/base/Think.Unbounded-d32-v2mix-cont.json"
STEP=9600

EXPERIMENT_ROOT="$EXPERIMENT_ROOT" STEP="$STEP" python - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ["EXPERIMENT_ROOT"])
step = int(os.environ["STEP"])
model = root / "base_checkpoints" / f"model_{step:06d}.pt"
meta_path = root / "base_checkpoints" / f"meta_{step:06d}.json"
tokenizer = root / "tokenizer" / "tokenizer.pkl"
for path in (model, meta_path, tokenizer):
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"Missing final artifact: {path}")
meta = json.loads(meta_path.read_text())
if meta.get("step") != step or meta.get("training_complete") is not True:
    raise SystemExit(f"Checkpoint {step} is not marked training_complete")
print(f"Final checkpoint PASS: step {step}")
PY

echo "Running full 20,971,520-token original validation BPB..."
if OUTPUT_JSON="$EXPERIMENT_ROOT/evals/val_bpb.json" STEP="$STEP" python - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["OUTPUT_JSON"])
record = json.loads(path.read_text()) if path.is_file() else {}
raise SystemExit(0 if record.get("step") == int(os.environ["STEP"]) and record.get("bpb", {}).get("val") is not None else 1)
PY
then
    echo "Keeping completed full validation BPB: $EXPERIMENT_ROOT/evals/val_bpb.json"
else
    bash runs/Think.Unbounded-d32-v2mix-cont.sh eval
fi

mkdir -p "$OUTPUT_DIR" "$VINTAGE_ROOT"
VINTAGE_ROOT="$VINTAGE_ROOT" python - <<'PY'
import os
from huggingface_hub import snapshot_download

root = os.environ["VINTAGE_ROOT"]
snapshot_download(
    repo_id="jbduran/vintage-core",
    repo_type="dataset",
    revision="v1.0.0",
    allow_patterns=["filtered/**", "restyled/**"],
    local_dir=root,
    token=os.environ.get("HF_TOKEN"),
)
print(f"Vintage CORE bundles prepared under {root}")
PY

run_core() {
    local bundle="$1"
    local bundle_dir="${2:-}"
    local output_json="$OUTPUT_DIR/$bundle.json"
    if OUTPUT_JSON="$output_json" STEP="$STEP" python - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["OUTPUT_JSON"])
record = json.loads(path.read_text()) if path.is_file() else {}
valid = (
    record.get("step") == int(os.environ["STEP"])
    and record.get("core_metric") is not None
    and isinstance(record.get("core_results"), dict)
    and isinstance(record.get("centered_results"), dict)
)
raise SystemExit(0 if valid else 1)
PY
    then
        echo "Keeping completed Vintage CORE bundle: $bundle"
        return
    fi
    local command=(
        python -u -m scripts.base_eval
        --eval=core
        --checkpoint-dir="$CHECKPOINT_DIR"
        --tokenizer-dir="$TOKENIZER_DIR"
        --step="$STEP"
        --max-per-task=-1
        --output-json="$output_json"
    )
    if [ -n "$bundle_dir" ]; then
        command+=(--core-bundle-dir="$bundle_dir")
    fi
    echo "Running full Vintage CORE bundle: $bundle"
    "${command[@]}"
}

run_core original
run_core filtered "$VINTAGE_ROOT/filtered"
run_core restyled "$VINTAGE_ROOT/restyled"

OUTPUT_DIR="$OUTPUT_DIR" EXPERIMENT_ROOT="$EXPERIMENT_ROOT" python - <<'PY'
import csv
import json
import os
from pathlib import Path

import wandb

output = Path(os.environ["OUTPUT_DIR"])
records = {name: json.loads((output / f"{name}.json").read_text())
           for name in ("original", "filtered", "restyled")}
common = sorted(set.intersection(*(set(record["centered_results"]) for record in records.values())))
if len(common) != 20:
    raise SystemExit(f"Expected a 20-task intersection, found {len(common)}")

rows = []
payload = {"eval/vintage_core/checkpoint_step": 9600}
for name, record in records.items():
    native = float(record["core_metric"])
    common20 = sum(float(record["centered_results"][task]) for task in common) / 20
    rows.append({"bundle": name, "native_core": native, "common_20_core": common20})
    payload[f"eval/vintage_core/{name}/native_core"] = native
    payload[f"eval/vintage_core/{name}/common_20_core"] = common20
    for task, value in record["core_results"].items():
        payload[f"eval/vintage_core/{name}/accuracy/{task}"] = float(value)
    for task, value in record["centered_results"].items():
        payload[f"eval/vintage_core/{name}/centered/{task}"] = float(value)

with (output / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=["bundle", "native_core", "common_20_core"])
    writer.writeheader()
    writer.writerows(rows)

run_info = json.loads((Path(os.environ["EXPERIMENT_ROOT"]) / "run.json").read_text())
run = wandb.init(
    entity="jbduran-thinkingmachinesncsu",
    project="think.nano",
    id=run_info["wandb_run_id"],
    resume="allow",
    name="Think.Unbounded-d32-v2mix-cont",
)
run.log(payload)
run.summary.update(payload)
run.finish()
print(json.dumps(rows, indent=2))
PY

python -u -m scripts.experiment sync --config "$CONFIG" --nproc-per-node 1
echo "All final evaluations complete: $EXPERIMENT_ROOT/evals"
