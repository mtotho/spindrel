#!/usr/bin/env bash
# Run live Codex/Claude harness parity diagnostics against deployed channels.
#
# Defaults target the main live server on localhost:8000 when run on the server.
# Override E2E_HOST/E2E_PORT/E2E_API_KEY for tunnels or other environments.
#
# Usage:
#   ./scripts/run_harness_parity_live.sh
#   ./scripts/run_harness_parity_live.sh --tier bridge
#   ./scripts/run_harness_parity_live.sh --tier plan
#   ./scripts/run_harness_parity_live.sh --tier heartbeat
#   ./scripts/run_harness_parity_live.sh --tier automation
#   ./scripts/run_harness_parity_live.sh --tier writes
#   ./scripts/run_harness_parity_live.sh --tier context
#   ./scripts/run_harness_parity_live.sh -k core

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TIER="${HARNESS_PARITY_TIER:-core}"
PYTEST_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tier)
            TIER="${2:?--tier requires one of: core, bridge, plan, heartbeat, automation, writes, context}"
            shift 2
            ;;
        --tier=*)
            TIER="${1#--tier=}"
            shift
            ;;
        *)
            PYTEST_ARGS+=("$1")
            shift
            ;;
    esac
done

cd "$PROJECT_ROOT"

if [[ -z "${E2E_API_KEY:-}" && -f "$PROJECT_ROOT/.env" ]]; then
    E2E_API_KEY="$(grep '^API_KEY=' "$PROJECT_ROOT/.env" | cut -d= -f2- || true)"
fi

if [[ -z "${E2E_API_KEY:-}" ]] && command -v docker >/dev/null 2>&1; then
    E2E_API_KEY="$(docker exec agent-server-agent-server-1 printenv API_KEY 2>/dev/null || true)"
fi

export E2E_MODE="external"
export E2E_HOST="${E2E_HOST:-127.0.0.1}"
export E2E_PORT="${E2E_PORT:-8000}"
export E2E_API_KEY="${E2E_API_KEY:?API key required; set E2E_API_KEY or run on the server/container host}"
export E2E_BOT_ID="${E2E_BOT_ID:-codex-bot}"
export E2E_REQUEST_TIMEOUT="${E2E_REQUEST_TIMEOUT:-300}"
export E2E_STARTUP_TIMEOUT="${E2E_STARTUP_TIMEOUT:-30}"

export HARNESS_PARITY_TIER="$TIER"
export HARNESS_PARITY_TIMEOUT="${HARNESS_PARITY_TIMEOUT:-300}"
export HARNESS_PARITY_CODEX_CHANNEL_ID="${HARNESS_PARITY_CODEX_CHANNEL_ID:-41fc9132-0e6a-4f95-bcf3-8b1edaf2dabc}"
export HARNESS_PARITY_CLAUDE_CHANNEL_ID="${HARNESS_PARITY_CLAUDE_CHANNEL_ID:-71eb14fd-a482-5bdd-a9a2-e60d9e951169}"

echo "=== Harness Live Parity ==="
echo "  Server: ${E2E_HOST}:${E2E_PORT}"
echo "  Tier:   ${HARNESS_PARITY_TIER}"
echo "  Codex:  ${HARNESS_PARITY_CODEX_CHANNEL_ID}"
echo "  Claude: ${HARNESS_PARITY_CLAUDE_CHANNEL_ID}"
echo ""

PYTEST_BIN=".venv/bin/pytest"
if [[ ! -x "$PYTEST_BIN" ]]; then
    PYTEST_BIN="pytest"
fi

exec "$PYTEST_BIN" tests/e2e/scenarios/test_harness_live_parity.py -q -rs "${PYTEST_ARGS[@]}"
