#!/bin/bash

# Resource-aware Vast.ai launcher for C3 robust v3 SFT from the completed Think.Unbounded d32 base.
#
# v3 over v2: `passes` equalises exposure at 3 per route (v2 gave 3/2/1), terminal
# punctuation gets its own 0.05 draw, robustness runs 2.5 epochs for ~5% of the
# mixture, and re-exposure re-renders instead of replaying byte-identical text.

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
    echo "No think.nano prebuilt Python environment found." >&2
    exit 2
fi

: "${HF_TOKEN:?HF_TOKEN must be set in .env or the environment}"
: "${WANDB_API_KEY:?WANDB_API_KEY must be set in .env or the environment}"

NPROC_PER_NODE="${NPROC_PER_NODE:-2}"
export NPROC_PER_NODE

python - <<'PY'
import os
import sys

try:
    import torch
    import wandb
except ImportError as exc:
    raise SystemExit(f"Prebuilt environment dependency missing: {exc}") from exc

if not torch.cuda.is_available():
    raise SystemExit("PyTorch cannot access CUDA in the selected prebuilt environment")
required = int(os.environ["NPROC_PER_NODE"])
visible = torch.cuda.device_count()
if visible < required:
    raise SystemExit(
        f"SFT requires {required} visible CUDA device(s); found {visible}. "
        "Clear any single-GPU CUDA_VISIBLE_DEVICES setting."
    )
if required not in {1, 2}:
    raise SystemExit(f"SFT supports one or two training ranks; received {required}")
minimum_gib = 70 if required == 1 else 35
minimum_bytes = minimum_gib * 1024**3
gpu_specs = []
for index in range(required):
    props = torch.cuda.get_device_properties(index)
    if props.total_memory < minimum_bytes:
        raise SystemExit(
            f"GPU {index} has {props.total_memory / 1024**3:.1f} GiB; "
            f"this topology requires at least {minimum_gib} GiB per GPU"
        )
    gpu_specs.append(
        f"{torch.cuda.get_device_name(index)} {props.total_memory / 1024**3:.1f}GiB"
    )
print(
    f"Runtime PASS: python={sys.executable}, torch={torch.__version__}, "
    f"wandb={wandb.__version__}, training_gpus={required} "
    f"({', '.join(gpu_specs)})"
)
PY

export NANOCHAT_BASE_DIR="${NANOCHAT_BASE_DIR:-/workspace/nanochat}"
export NANOCHAT_EXPERIMENT_ROOT="${NANOCHAT_EXPERIMENT_ROOT:-$NANOCHAT_BASE_DIR/experiments}"
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"
export NANOCHAT_DIST_OPTIMIZER_LOW_MEMORY="${NANOCHAT_DIST_OPTIMIZER_LOW_MEMORY:-0}"

PARENT_EXPERIMENT_ID="Think.Unbounded-d32-v2mix-cont"
PARENT_STEP=9600
BASE_CONFIG="configs/base/Think.Unbounded-d32-v2mix-cont.json"
SFT_CONFIG="configs/sft/pre1930-curriculum-c3-robust-v3-parallel-2xa100-80gb.json"

git merge-base --is-ancestor 792af43 HEAD || {
    echo "Checkout lacks required staged-curriculum noise fix 792af43; pull current dev." >&2
    exit 2
}
git merge-base --is-ancestor b77af10 HEAD || {
    echo "Checkout lacks the system-prompting merge b77af10; pull current dev." >&2
    exit 2
}
git merge-base --is-ancestor 7049b4d HEAD || {
    echo "Checkout lacks the v3 passes/re-render curriculum 7049b4d; pull current dev." >&2
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
if curriculum.get("noise", {}).get("end_punct_rate") != 0.05:
    raise SystemExit("C3 robust v3 data.curriculum.noise.end_punct_rate must be 0.05")
if curriculum.get("passes") != 3:
    raise SystemExit("C3 robust v3 data.curriculum.passes must be 3")
if curriculum.get("epochs") is not None:
    raise SystemExit("C3 robust v3 must size exposure with passes, not epochs")
if curriculum.get("robustness", {}).get("epochs") != 2.5:
    raise SystemExit("C3 robust v3 robustness.epochs must be 2.5 (~5% of the mixture)")
expected_routes = {
    "conversation_qa",
    "conversation_multiturn",
    "unparseable_qa",
    "typo_qa",
    "era_qa",
}
actual_routes = set(curriculum.get("robustness", {}).get("routes", {}))
if actual_routes != expected_routes:
    raise SystemExit(
        f"C3 robustness routes are {sorted(actual_routes)}, expected {sorted(expected_routes)}"
    )
if sft.get("training", {}).get("load_optimizer") != 0:
    raise SystemExit("C3 robust training.load_optimizer must be 0")
if sft.get("training", {}).get("device_batch_size") != 2:
    raise SystemExit("D32 C3 robust training.device_batch_size must be 2 per 80 GB rank")
if sft.get("wandb", {}).get("group") != "think-d32":
    raise SystemExit("D32 C3 robust W&B group must be think-d32")

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
# v3 rebuilds every stage mixture under a stage-scoped noise seed, so cumulativeness
# is a property of which routes are present, not of Task object identity.
def _routes_in(mixture):
    seeds = [getattr(t, "noise_seed", None) for t in mixture.tasks]
    return {s.split(":")[2] for s in seeds if s and len(s.split(":")) > 2}
stage_routes = [_routes_in(mixture) for mixture in sequence.tasks]
if any(not earlier.issubset(later) for earlier, later in zip(stage_routes, stage_routes[1:])):
    raise SystemExit("Staged curriculum is not cumulative")
# Noised Tasks must be rebuilt per stage. Authentic conversations have no noise
# path, so those are legitimately carried over as the same object.
def _noised(mixture):
    return {id(t) for t in mixture.tasks if getattr(t, "noise_seed", None) is not None}
if any(_noised(sequence.tasks[i]) & _noised(sequence.tasks[i + 1])
       for i in range(len(sequence.tasks) - 1)):
    raise SystemExit("v3 must rebuild each stage; a noised Task was reused across stages")
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
if any(task.noise_end_punct_rate != 0.05 for task in noisy_tasks):
    raise SystemExit("Executed _build_staged path did not propagate end_punct_rate=0.05")
# The v3 change: a row met again at a later stage must be battered differently.
probe = "What is the reason that the tides follow the moon?"
renders = {
    synth.noise_text(probe, f"1930:s{stage}:knowledge_qa:0:0", 0.3, 0.05)
    for stage in range(len(sequence.tasks))
}
if len(renders) < 2:
    raise SystemExit("Re-exposure is not re-rendering; stage seed did not reach the noise")

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
print("C3 v3 PASS: passes=3, end_punct_rate=0.05, robustness 2.5 epochs, re-exposure re-renders")
print(f"Hosted parent PASS: {parent_id} complete at configured final step {parent_step}")
PY

python -u -m scripts.experiment prepare \
    --config "$SFT_CONFIG" \
    --parent-experiment-id "$PARENT_EXPERIMENT_ID" \
    --parent-step "$PARENT_STEP" \
    --nproc-per-node "$NPROC_PER_NODE"

TRAIN_ARGS=()
if [ "${DEFER_CHATCORE:-0}" = "1" ]; then
    TRAIN_ARGS+=(--defer-chatcore)
fi
python -u -m scripts.experiment train \
    --config "$SFT_CONFIG" \
    --parent-experiment-id "$PARENT_EXPERIMENT_ID" \
    --parent-step "$PARENT_STEP" \
    --nproc-per-node "$NPROC_PER_NODE" \
    "${TRAIN_ARGS[@]}"
