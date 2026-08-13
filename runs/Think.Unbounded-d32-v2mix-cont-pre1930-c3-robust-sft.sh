#!/bin/bash

# Vast.ai launcher for C3 robust SFT from the completed Think.Unbounded d32 base.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

: "${HF_TOKEN:?HF_TOKEN must be set in .env or the environment}"
: "${WANDB_API_KEY:?WANDB_API_KEY must be set in .env or the environment}"

export NANOCHAT_BASE_DIR="${NANOCHAT_BASE_DIR:-/workspace/nanochat}"
export NANOCHAT_EXPERIMENT_ROOT="${NANOCHAT_EXPERIMENT_ROOT:-$NANOCHAT_BASE_DIR/experiments}"

PARENT_EXPERIMENT_ID="Think.Unbounded-d32-v2mix-cont"
PARENT_STEP=9600
BASE_CONFIG="configs/base/Think.Unbounded-d32-v2mix-cont.json"
SFT_CONFIG="configs/sft/pre1930-curriculum-c3-robust.json"

git merge-base --is-ancestor 792af43 HEAD || {
    echo "Checkout lacks required staged-curriculum noise fix 792af43; pull current dev." >&2
    exit 2
}
git merge-base --is-ancestor b77af10 HEAD || {
    echo "Checkout lacks the system-prompting merge b77af10; pull current dev." >&2
    exit 2
}

BASE_CONFIG="$BASE_CONFIG" SFT_CONFIG="$SFT_CONFIG" \
PARENT_EXPERIMENT_ID="$PARENT_EXPERIMENT_ID" PARENT_STEP="$PARENT_STEP" \
python -u - <<'PY'
import importlib
import json
import os
from pathlib import Path

from huggingface_hub import hf_hub_download
from scripts.experiment import Experiment, _complete_steps, _config_iterations

base_path = Path(os.environ["BASE_CONFIG"])
sft_path = Path(os.environ["SFT_CONFIG"])
parent_id = os.environ["PARENT_EXPERIMENT_ID"]
parent_step = int(os.environ["PARENT_STEP"])
base = json.loads(base_path.read_text())
sft = json.loads(sft_path.read_text())

if base.get("experiment_id") != parent_id:
    raise SystemExit(f"Base config experiment_id is not {parent_id!r}")
configured_final = _config_iterations(base)
if configured_final != parent_step:
    raise SystemExit(
        f"Configured final base step is {configured_final}, expected exactly {parent_step}"
    )

curriculum = sft.get("data", {}).get("curriculum", {})
if curriculum.get("mode") != "staged":
    raise SystemExit("C3 robust must execute the staged curriculum path")
if curriculum.get("noise", {}).get("rate") != 0.3:
    raise SystemExit("C3 robust data.curriculum.noise.rate must be 0.3")
expected_routes = {"conversation_qa", "unparseable_qa", "era_qa"}
actual_routes = set(curriculum.get("robustness", {}).get("routes", {}))
if actual_routes != expected_routes:
    raise SystemExit(
        f"C3 robustness routes are {sorted(actual_routes)}, expected {sorted(expected_routes)}"
    )
if sft.get("training", {}).get("load_optimizer") != 0:
    raise SystemExit("C3 robust training.load_optimizer must be 0")

# Exercise the implementation that chat_sft imports, without downloading SFT rows.
synth = importlib.import_module("tasks.synth-pre1930")
required = (
    "_build_staged", "_epoch_tasks", "_noised_conversation",
    "_robustness_tasks", "noise_text",
)
missing = [name for name in required if not hasattr(synth, name)]
if missing:
    raise SystemExit(f"Checkout lacks staged robustness/noise implementation: {missing}")

conversation = {
    "messages": [
        {"role": "user", "content": "What is the reason that the tides follow the moon?"},
        {"role": "assistant", "content": "The answer must remain byte-identical."},
    ]
}
first = synth._noised_conversation(conversation, "determinism", 1.0)
second = synth._noised_conversation(conversation, "determinism", 1.0)
if first != second:
    raise SystemExit("Noise is not deterministic for a fixed seed")
if first["messages"][1] != conversation["messages"][1]:
    raise SystemExit("Noise corrupted an assistant target")
if not any(
    synth._noised_conversation(conversation, f"probe:{i}", 1.0)["messages"][0]["content"]
    != conversation["messages"][0]["content"]
    for i in range(64)
):
    raise SystemExit("Noise path did not alter any probed user turn")

row = {
    "question": "Why does the tide rise?",
    "answer": "Because of gravitation.",
    "doc_index": "probe",
}
original_select = synth.select_route_rows
original_robustness = synth._load_robustness_rows
original_authentic = synth._authentic_task
try:
    synth.select_route_rows = lambda *args, **kwargs: [dict(row)]
    synth._load_robustness_rows = lambda route: [dict(row)]
    synth._authentic_task = lambda *args, **kwargs: synth._RowListTask([dict(row)])
    summary = {"routes": {}}
    sequence = synth._build_staged(curriculum, 1930, lambda route: None, summary)
finally:
    synth.select_route_rows = original_select
    synth._load_robustness_rows = original_robustness
    synth._authentic_task = original_authentic

if len(sequence.tasks) != len(curriculum.get("stages", [])):
    raise SystemExit("Executed _build_staged path produced the wrong stage count")
task_ids = [{id(task) for task in mixture.tasks} for mixture in sequence.tasks]
if any(not earlier.issubset(later) for earlier, later in zip(task_ids, task_ids[1:])):
    raise SystemExit("Staged curriculum is not cumulative")
added_routes = [
    {entry["route"] for entry in stage["added"]}
    for stage in summary["stages"]
]
robust_stage = int(curriculum["robustness"].get("stage", 0))
if not expected_routes.issubset(added_routes[robust_stage]):
    raise SystemExit("Executed _build_staged path omitted robustness routes")
if any(expected_routes & routes for i, routes in enumerate(added_routes) if i != robust_stage):
    raise SystemExit("Robustness routes were re-added instead of cumulatively preserved")
noisy_tasks = [
    task for mixture in sequence.tasks for task in mixture.tasks
    if getattr(task, "noise_seed", None) is not None
]
if not noisy_tasks or any(task.noise_rate != 0.3 for task in noisy_tasks):
    raise SystemExit("Executed _build_staged path did not propagate noise.rate=0.3")

# Require this exact hosted step to have model, metadata, and optimizer state.
experiment = Experiment(
    sft_path,
    parent_experiment_id=parent_id,
    parent_step=parent_step,
    nproc_per_node=1,
)
experiment.validate_config()
parent_prefix = experiment.parent_hf_prefix()
checkpoint_prefix = f"{parent_prefix}/base_checkpoints/"
remote_files = experiment.remote_files(strict=True, path_in_repo=parent_prefix)
complete = _complete_steps(remote_files, checkpoint_prefix)
if parent_step not in complete:
    raise SystemExit(
        f"Hosted parent {parent_id} step {parent_step} is incomplete; "
        "model, metadata, and optimizer state are required"
    )
meta_file = hf_hub_download(
    experiment.hf_repo,
    f"{checkpoint_prefix}meta_{parent_step:06d}.json",
    repo_type="model",
    token=os.environ.get("HF_TOKEN"),
)
meta = json.loads(Path(meta_file).read_text())
if meta.get("step") != parent_step or meta.get("training_complete") is not True:
    raise SystemExit(
        f"Hosted checkpoint step {parent_step} is not marked training_complete"
    )
if meta.get("experiment_id") != parent_id:
    raise SystemExit(
        f"Hosted checkpoint belongs to {meta.get('experiment_id')!r}, not {parent_id!r}"
    )

print("C3 robust implementation PASS: deterministic user-only noise, untouched targets")
print("C3 staged curriculum PASS: robustness routes present and cumulative")
print(f"Hosted parent PASS: {parent_id} complete at configured final step {parent_step}")
PY

python -u -m scripts.experiment prepare \
    --config "$SFT_CONFIG" \
    --parent-experiment-id "$PARENT_EXPERIMENT_ID" \
    --parent-step "$PARENT_STEP"

python -u -m scripts.experiment train \
    --config "$SFT_CONFIG" \
    --parent-experiment-id "$PARENT_EXPERIMENT_ID" \
    --parent-step "$PARENT_STEP"
