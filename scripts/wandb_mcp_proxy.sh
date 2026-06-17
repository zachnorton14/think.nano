#!/usr/bin/env zsh
set -eo pipefail

REPO_ENV="/Users/jonathanduran-ortiz/Developer/think.nano/.env"

# mcp-remote logs custom headers on startup. Keep the API key out of Codex logs.
exec 2> >(sed -E 's/Bearer [^"]+/Bearer [REDACTED]/g' >&2)

if [[ ! -f "$REPO_ENV" ]]; then
  echo "Missing W&B environment file: $REPO_ENV" >&2
  exit 1
fi

set -a
source "$REPO_ENV"
set +a

if [[ -z "${WANDB_API_KEY:-}" ]]; then
  echo "WANDB_API_KEY is not set in $REPO_ENV" >&2
  exit 1
fi

exec npx -y mcp-remote https://mcp.withwandb.com/mcp \
  --header "Authorization: Bearer ${WANDB_API_KEY}"
