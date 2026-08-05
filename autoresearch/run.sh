#!/usr/bin/env bash
#
# One-time bring-up for an autoresearch box: check the GPU, build the token cache,
# and run the baseline experiment.
#
#   bash autoresearch/run.sh
#
# Env:
#   NUM_SHARDS           training shards to download (default 40, ~3.1 GB, ~2.7B tokens)
#   AUTORESEARCH_PYTHON  python to use (default: container venv if present, else `uv run python`)
#
# Unlike runs/*.sh this takes no config: autoresearch has one fixed setup and one
# metric. After this finishes, start the agent and point it at autoresearch/program.md.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

NUM_SHARDS="${NUM_SHARDS:-40}"
if [[ -n "${AUTORESEARCH_PYTHON:-}" ]]; then
    PYTHON="$AUTORESEARCH_PYTHON"
elif [[ -x /opt/think-nano-venv/bin/python ]]; then
    PYTHON=/opt/think-nano-venv/bin/python
else
    PYTHON="uv run python"
fi

echo "python:     $PYTHON"
echo "num shards: $NUM_SHARDS"

$PYTHON - <<'PY'
import torch
assert torch.cuda.is_available(), "No CUDA device visible."
cap = torch.cuda.get_device_capability()
print(f"gpu:        {torch.cuda.get_device_name(0)} (sm{cap[0]}{cap[1]}), "
      f"{torch.cuda.device_count()} visible")
if cap != (9, 0):
    print("note:       tuned on H100 (sm90); other GPUs take a different "
          "flash-attention path and the numbers will not match")
PY

echo
$PYTHON autoresearch/prepare.py --num-shards "$NUM_SHARDS"

echo
echo "Running the baseline experiment (~6 min)..."
$PYTHON autoresearch/train.py > run.log 2>&1 || { tail -n 40 run.log; exit 1; }
grep "^val_bpb:\|^training_seconds:\|^peak_vram_mb:\|^mfu_percent:\|^num_steps:" run.log \
    || { tail -n 40 run.log; exit 1; }

echo
echo "Baseline is in. Start the agent and prompt it with:"
echo "  Hi have a look at autoresearch/program.md and let's kick off a new experiment!"
