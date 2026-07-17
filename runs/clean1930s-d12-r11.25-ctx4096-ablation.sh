#!/usr/bin/env bash

# Run one member of the matched d12 4K attention ablation pair.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE="${1:-}"

case "$MODE" in
    sssl)
        CONFIG=clean1930s-d12-r11.25-ctx4096-sssl-fulltok-ablation-v1.json
        ;;
    full)
        CONFIG=clean1930s-d12-r11.25-ctx4096-full-fulltok-ablation-v1.json
        ;;
    *)
        echo "Usage: $0 {sssl|full}" >&2
        exit 2
        ;;
esac

export BASE_CONFIG_PATH="$SCRIPT_DIR/../configs/base/$CONFIG"
export NPROC_PER_NODE="${NPROC_PER_NODE:-1}"
export ALLOW_SINGLE_GPU=1
export REQUIRE_FULL_NVLINK="${REQUIRE_FULL_NVLINK:-0}"
if [ -d /workspace ]; then
    DEFAULT_BASE_DIR=/workspace/nanochat
else
    DEFAULT_BASE_DIR="$HOME/.cache/nanochat"
fi
export TORCHINDUCTOR_CACHE_DIR="${TORCHINDUCTOR_CACHE_DIR:-${NANOCHAT_BASE_DIR:-$DEFAULT_BASE_DIR}/torchinductor-d12-ctx4096-$MODE}"

exec bash "$SCRIPT_DIR/clean1930s-d24-r12.sh"
