#!/usr/bin/env bash
# Run live native Spindrel plan-mode diagnostics against a deployed channel.
#
# Defaults target the main live server on localhost:8000 when run on the server.
# Override E2E_HOST/E2E_PORT/E2E_API_KEY for tunnels or other environments.
#
# Usage:
#   ./scripts/run_spindrel_plan_live.sh
#   ./scripts/run_spindrel_plan_live.sh --tier questions
#   ./scripts/run_spindrel_plan_live.sh --tier publish
#   ./scripts/run_spindrel_plan_live.sh --tier approve
#   ./scripts/run_spindrel_plan_live.sh --tier replay
#   ./scripts/run_spindrel_plan_live.sh -k publish_plan

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TIER="${SPINDREL_PLAN_TIER:-core}"
PYTEST_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tier)
            TIER="${2:?--tier requires one of: core, questions, publish, approve, answers, progress, replan, guardrails, replay}"
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

if [[ -z "${E2E_API_KEY:-}" ]] && command -v docker >/dev/null 2>&1; then
    E2E_API_KEY="$(docker exec agent-server-agent-server-1 printenv API_KEY 2>/dev/null || true)"
fi

if [[ -z "${E2E_API_KEY:-}" && -f "$PROJECT_ROOT/.env" ]]; then
    E2E_API_KEY="$(grep '^API_KEY=' "$PROJECT_ROOT/.env" | cut -d= -f2- || true)"
fi

export E2E_MODE="external"
export E2E_HOST="${E2E_HOST:-127.0.0.1}"
export E2E_PORT="${E2E_PORT:-8000}"
export E2E_API_KEY="${E2E_API_KEY:?API key required; set E2E_API_KEY or run on the server/container host}"
export E2E_BOT_ID="${E2E_BOT_ID:-default}"
export E2E_REQUEST_TIMEOUT="${E2E_REQUEST_TIMEOUT:-300}"
export E2E_STARTUP_TIMEOUT="${E2E_STARTUP_TIMEOUT:-120}"
export SPINDREL_PLAN_HEALTH_WAIT_TIMEOUT="${SPINDREL_PLAN_HEALTH_WAIT_TIMEOUT:-120}"

export SPINDREL_PLAN_TIER="$TIER"
export SPINDREL_PLAN_TIMEOUT="${SPINDREL_PLAN_TIMEOUT:-450}"
export SPINDREL_PLAN_CHANNEL_ID="${SPINDREL_PLAN_CHANNEL_ID:-67a06926-87e6-40fb-b85b-7eac36c74b98}"
export SPINDREL_PLAN_BOT_ID="${SPINDREL_PLAN_BOT_ID:-e2e-bot}"
export SPINDREL_PLAN_MODEL="${SPINDREL_PLAN_MODEL:-gpt-5.4-mini}"
export SPINDREL_PLAN_ARTIFACT_DIR="${SPINDREL_PLAN_ARTIFACT_DIR:-/tmp/spindrel-plan-parity}"

wait_for_server_health() {
    local url="http://${E2E_HOST}:${E2E_PORT}/health"
    local deadline=$((SECONDS + SPINDREL_PLAN_HEALTH_WAIT_TIMEOUT))
    while (( SECONDS < deadline )); do
        if command -v curl >/dev/null 2>&1; then
            if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
                return 0
            fi
        else
            if python - "$url" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

urllib.request.urlopen(sys.argv[1], timeout=5).read(1)
PY
            then
                return 0
            fi
        fi
        sleep 2
    done
    echo "Timed out waiting for server health at $url after ${SPINDREL_PLAN_HEALTH_WAIT_TIMEOUT}s" >&2
    if command -v curl >/dev/null 2>&1; then
        curl -v --max-time 5 "$url" >&2 || true
    fi
    return 1
}

echo "=== Native Spindrel Plan Mode Live ==="
echo "  Server:   ${E2E_HOST}:${E2E_PORT}"
echo "  Tier:     ${SPINDREL_PLAN_TIER}"
echo "  Channel:  ${SPINDREL_PLAN_CHANNEL_ID}"
echo "  Bot:      ${SPINDREL_PLAN_BOT_ID}"
echo "  Model:    ${SPINDREL_PLAN_MODEL}"
echo "  Artifacts:${SPINDREL_PLAN_ARTIFACT_DIR}"
echo "  Timeout:  ${SPINDREL_PLAN_TIMEOUT}"
echo "  Health wait: ${SPINDREL_PLAN_HEALTH_WAIT_TIMEOUT}"
echo ""

PYTEST_BIN=".venv/bin/pytest"
if [[ ! -x "$PYTEST_BIN" ]]; then
    PYTEST_BIN="pytest"
fi

wait_for_server_health

exec "$PYTEST_BIN" tests/e2e/scenarios/test_spindrel_plan_live.py -q -rs "${PYTEST_ARGS[@]}"
