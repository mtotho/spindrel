#!/usr/bin/env bash
# Run E2E tests against the live Spindrel server.
#
# Usage:
#   ./scripts/run_e2e_live.sh                    # full suite
#   ./scripts/run_e2e_live.sh test_api_contract   # single file
#   ./scripts/run_e2e_live.sh -k "carapaces"      # keyword filter
#
# Environment (override via env vars or .env):
#   E2E_HOST       — server hostname (default: localhost)
#   E2E_PORT       — server port (default: 8000)
#   E2E_API_KEY    — admin API key (loaded from .env if not set)
#   E2E_BOT_ID     — default bot for chat tests (default: default)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Load .env if API key not already set
if [[ -z "${E2E_API_KEY:-}" ]] && [[ -f "$PROJECT_ROOT/.env" ]]; then
    E2E_API_KEY=$(grep '^API_KEY=' "$PROJECT_ROOT/.env" | cut -d= -f2)
fi

# Defaults for live server
export E2E_MODE="external"
export E2E_HOST="${E2E_HOST:-localhost}"
export E2E_PORT="${E2E_PORT:-8000}"
export E2E_API_KEY="${E2E_API_KEY:?API key required — set E2E_API_KEY or add API_KEY to .env}"
export E2E_BOT_ID="${E2E_BOT_ID:-e2e}"
export E2E_DEFAULT_MODEL="${E2E_DEFAULT_MODEL:-gemini/gemini-2.5-flash-lite}"
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
