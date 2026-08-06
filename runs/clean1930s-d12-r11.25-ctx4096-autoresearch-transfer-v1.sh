#!/usr/bin/env bash

# First production-scale transfer of the autoresearch findings on one H100.
# Each run trains at 4K context, skips CORE, runs canonical full validation BPB,
# logs to one W&B group, and uploads checkpoints/evaluation metadata to HF.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$SCRIPT_DIR/../configs/base"
MODE="${1:-all}"

if [ -d /workspace ]; then
    DEFAULT_BASE_DIR=/workspace/nanochat
else
    DEFAULT_BASE_DIR="$HOME/.cache/nanochat"
fi

export NPROC_PER_NODE=1
export ALLOW_SINGLE_GPU=1
export REQUIRE_FULL_NVLINK=0
export MIN_FREE_GIB="${MIN_FREE_GIB:-80}"
export RUN_FINAL_BPB=1
export TORCHINDUCTOR_CACHE_DIR="${TORCHINDUCTOR_CACHE_DIR:-${NANOCHAT_BASE_DIR:-$DEFAULT_BASE_DIR}/torchinductor-d12-ctx4096-artransfer-v1}"

run_one() {
    local config="$1"
    echo "Starting $config"
    BASE_CONFIG_PATH="$CONFIG_DIR/$config" \
        bash "$SCRIPT_DIR/clean1930s-d24-r12.sh"
}

case "$MODE" in
    baseline42)
        run_one clean1930s-d12-r11.25-ctx4096-sssl-fulltok-artransfer-baseline-s42-v1.json
        ;;
    baseline43)
        run_one clean1930s-d12-r11.25-ctx4096-sssl-fulltok-artransfer-baseline-s43-v1.json
        ;;
    momentum083)
        run_one clean1930s-d12-r11.25-ctx4096-sssl-fulltok-artransfer-muon083-s42-v1.json
        ;;
    momentum085)
        run_one clean1930s-d12-r11.25-ctx4096-sssl-fulltok-artransfer-muon085-s42-v1.json
        ;;
    momentum090)
        run_one clean1930s-d12-r11.25-ctx4096-sssl-fulltok-artransfer-muon090-s42-v1.json
        ;;
    swiglu)
        run_one clean1930s-d12-r11.25-ctx4096-sssl-fulltok-artransfer-swiglu-s42-v1.json
        ;;
    baselines)
        run_one clean1930s-d12-r11.25-ctx4096-sssl-fulltok-artransfer-baseline-s42-v1.json
        run_one clean1930s-d12-r11.25-ctx4096-sssl-fulltok-artransfer-baseline-s43-v1.json
        ;;
    # Full queue: anchor and stability check first, then three points mapping the
    # momentum dose-response against production's 0.85->0.97 ramp. 0.83 was
    # autoresearch's best value, 0.85 the adjacent accepted point (the two are ~1
    # sigma apart, on the same plateau), and 0.90 is production's own warmdown
    # floor, which separates "does not transfer" from "overshot".
    # ~5 runs, roughly 4 hours on one H100.
    #
    # SwiGLU is deliberately not here; run `swiglu` explicitly if you want it.
    # dev/LOG.md:273 records parameter-matched 8/3x SwiGLU as worse at both d12 and
    # d24, autoresearch's own parameter-matched point moved only -0.0004 (~0.5 sigma),
    # and five of its six hidden-size variants sit inside a one-sigma band with a
    # single outlier at 2.75x. Not enough signal to spend a run on.
    all)
        run_one clean1930s-d12-r11.25-ctx4096-sssl-fulltok-artransfer-baseline-s42-v1.json
        run_one clean1930s-d12-r11.25-ctx4096-sssl-fulltok-artransfer-baseline-s43-v1.json
        run_one clean1930s-d12-r11.25-ctx4096-sssl-fulltok-artransfer-muon083-s42-v1.json
        run_one clean1930s-d12-r11.25-ctx4096-sssl-fulltok-artransfer-muon085-s42-v1.json
        run_one clean1930s-d12-r11.25-ctx4096-sssl-fulltok-artransfer-muon090-s42-v1.json
        ;;
    *)
        echo "Usage: $0 {baseline42|baseline43|momentum083|momentum085|momentum090|swiglu|baselines|all}" >&2
        exit 2
        ;;
esac
