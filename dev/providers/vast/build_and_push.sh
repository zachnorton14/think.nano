#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <registry/repository> [--no-push]" >&2
    exit 2
fi

REPOSITORY="$1"
if command -v sha256sum >/dev/null 2>&1; then
    LOCK_SHA="$(sha256sum "$REPO_ROOT/uv.lock" | awk '{print $1}')"
else
    LOCK_SHA="$(shasum -a 256 "$REPO_ROOT/uv.lock" | awk '{print $1}')"
fi
IMAGE="$REPOSITORY:cu128-torch291-${LOCK_SHA:0:12}"
PUSH=1
if [ "${2:-}" = "--no-push" ]; then
    PUSH=0
fi

ARGS=(
    --platform linux/amd64
    --file "$SCRIPT_DIR/Dockerfile"
    --build-arg "LOCK_SHA=$LOCK_SHA"
    --tag "$IMAGE"
)
if [ "$PUSH" = "1" ]; then
    ARGS+=(--push)
else
    ARGS+=(--load)
fi

docker buildx build "${ARGS[@]}" "$REPO_ROOT"
echo "$IMAGE"
