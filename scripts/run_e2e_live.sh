#!/usr/bin/env bash
# Run E2E tests against a live Spindrel server.
#
# By default, targets the dedicated E2E instance (port 18000).
# Use --production to target the main instance (port 8000) instead.
#
# Usage:
#   ./scripts/run_e2e_live.sh                    # full suite (E2E instance)
#   ./scripts/run_e2e_live.sh --production       # target main instance
#   ./scripts/run_e2e_live.sh test_api_contract   # single file
#   ./scripts/run_e2e_live.sh -k "carapaces"      # keyword filter
#
# Environment (override via env vars):
#   E2E_HOST       — server hostname (default: localhost)
#   E2E_PORT       — server port (default: 18000)
#   E2E_API_KEY    — admin API key (loaded from E2E instance .env if not set)
#   E2E_BOT_ID     — default bot for chat tests (default: e2e)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Default to E2E instance; --production switches to main
E2E_INSTANCE_DIR="${E2E_INSTANCE_DIR:-$HOME/spindrel-e2e}"
DEFAULT_PORT=18000

if [[ "${1:-}" == "--production" ]]; then
    E2E_INSTANCE_DIR="$PROJECT_ROOT"
    DEFAULT_PORT=8000
    shift
fi

# Load API key from the target instance's .env if not already set
if [[ -z "${E2E_API_KEY:-}" ]] && [[ -f "$E2E_INSTANCE_DIR/.env" ]]; then
    E2E_API_KEY=$(grep '^API_KEY=' "$E2E_INSTANCE_DIR/.env" | cut -d= -f2)
fi

# Defaults
export E2E_MODE="external"
export E2E_HOST="${E2E_HOST:-localhost}"
export E2E_PORT="${E2E_PORT:-$DEFAULT_PORT}"
export E2E_API_KEY="${E2E_API_KEY:?API key required — set E2E_API_KEY or add API_KEY to target .env}"
export E2E_BOT_ID="${E2E_BOT_ID:-e2e}"
export E2E_DEFAULT_MODEL="${E2E_DEFAULT_MODEL:-gemini-2.5-flash-lite}"
export E2E_REQUEST_TIMEOUT="${E2E_REQUEST_TIMEOUT:-120}"

echo "=== E2E Live Server Tests ==="
echo "  Server: ${E2E_HOST}:${E2E_PORT}"
echo "  Bot:    ${E2E_BOT_ID}"
echo "  Model:  ${E2E_DEFAULT_MODEL}"
echo ""

cd "$PROJECT_ROOT"

# Build pytest args
PYTEST_ARGS=(
    tests/e2e/
    -v
    --tb=short
    -x  # stop on first failure for fast feedback
)

# If first arg looks like a test file name, add it as a filter
if [[ ${1:-} == test_* ]]; then
    PYTEST_ARGS+=(-k "$1")
    shift
fi

# Pass remaining args through to pytest
PYTEST_ARGS+=("$@")

exec pytest "${PYTEST_ARGS[@]}"
