#!/usr/bin/env bash
# Run live Codex/Claude harness parity diagnostics against deployed channels.
#
# Defaults target the main live server on localhost:8000 when run on the server.
# Override E2E_HOST/E2E_PORT/E2E_API_KEY for tunnels or other environments.
#
# Usage:
#   ./scripts/run_harness_parity_live.sh
#   ./scripts/run_harness_parity_live.sh --tier bridge
#   ./scripts/run_harness_parity_live.sh --tier terminal
#   ./scripts/run_harness_parity_live.sh --tier plan
#   ./scripts/run_harness_parity_live.sh --tier heartbeat
#   ./scripts/run_harness_parity_live.sh --tier automation
#   ./scripts/run_harness_parity_live.sh --tier writes
#   ./scripts/run_harness_parity_live.sh --tier context
#   ./scripts/run_harness_parity_live.sh --tier project
#   ./scripts/run_harness_parity_live.sh --tier memory
#   ./scripts/run_harness_parity_live.sh --tier skills
#   ./scripts/run_harness_parity_live.sh --tier replay
#   ./scripts/run_harness_parity_live.sh -k core

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TIER="${HARNESS_PARITY_TIER:-core}"
PYTEST_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tier)
            TIER="${2:?--tier requires one of: core, bridge, terminal, plan, heartbeat, automation, writes, context, project, memory, skills, replay}"
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
export HARNESS_PARITY_HEALTH_WAIT_TIMEOUT="${HARNESS_PARITY_HEALTH_WAIT_TIMEOUT:-120}"

export HARNESS_PARITY_TIER="$TIER"
export HARNESS_PARITY_TIMEOUT="${HARNESS_PARITY_TIMEOUT:-300}"
export HARNESS_PARITY_CODEX_CHANNEL_ID="${HARNESS_PARITY_CODEX_CHANNEL_ID:-41fc9132-0e6a-4f95-bcf3-8b1edaf2dabc}"
export HARNESS_PARITY_CLAUDE_CHANNEL_ID="${HARNESS_PARITY_CLAUDE_CHANNEL_ID:-71eb14fd-a482-5bdd-a9a2-e60d9e951169}"
export HARNESS_PARITY_AGENT_CONTAINER="${HARNESS_PARITY_AGENT_CONTAINER:-agent-server-agent-server-1}"
export HARNESS_PARITY_PLAYWRIGHT_HOST="${HARNESS_PARITY_PLAYWRIGHT_HOST:-playwright-local}"
export HARNESS_PARITY_PLAYWRIGHT_CONTAINER="${HARNESS_PARITY_PLAYWRIGHT_CONTAINER:-spindrel-local-browser-automation-playwright-1}"
export HARNESS_PARITY_PROJECT_PATH="${HARNESS_PARITY_PROJECT_PATH:-common/projects}"
export HARNESS_PARITY_PROJECT_TIMEOUT="${HARNESS_PARITY_PROJECT_TIMEOUT:-600}"

wait_for_server_health() {
    local url="http://${E2E_HOST}:${E2E_PORT}/health"
    local deadline=$((SECONDS + HARNESS_PARITY_HEALTH_WAIT_TIMEOUT))
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
    echo "Timed out waiting for server health at $url after ${HARNESS_PARITY_HEALTH_WAIT_TIMEOUT}s" >&2
    if command -v curl >/dev/null 2>&1; then
        curl -v --max-time 5 "$url" >&2 || true
    fi
    return 1
}

preflight_api_surface() {
    local base_url="http://${E2E_HOST}:${E2E_PORT}"
    local openapi
    if command -v curl >/dev/null 2>&1; then
        openapi="$(curl -fsS --max-time 10 "$base_url/openapi.json" 2>/dev/null || true)"
    else
        openapi="$(python - "$base_url/openapi.json" <<'PY' 2>/dev/null || true
import sys
import urllib.request

print(urllib.request.urlopen(sys.argv[1], timeout=10).read().decode())
PY
)"
    fi
    if [[ -z "$openapi" ]]; then
        echo "Harness parity preflight failed: could not read $base_url/openapi.json" >&2
        return 1
    fi

    local openapi_tmp
    openapi_tmp="$(mktemp)"
    printf '%s' "$openapi" > "$openapi_tmp"
    if ! python - "$HARNESS_PARITY_TIER" "$openapi_tmp" <<'PY'
import json
import sys

tier = sys.argv[1]
with open(sys.argv[2], "r", encoding="utf-8") as fh:
    doc = json.load(fh)
paths = set(doc.get("paths") or {})

tier_order = {
    "core": 0,
    "bridge": 1,
    "terminal": 2,
    "plan": 3,
    "heartbeat": 4,
    "automation": 5,
    "writes": 6,
    "context": 7,
    "project": 8,
    "memory": 9,
    "skills": 10,
    "replay": 11,
}

required = ["/api/v1/channels/{channel_id}/sessions"]
if tier_order.get(tier, 0) >= tier_order["terminal"]:
    required.append("/api/v1/admin/docker-stacks")

missing = [path for path in required if path not in paths]
if missing:
    print("Harness parity preflight failed: deployed API is missing required routes:", file=sys.stderr)
    for path in missing:
        print(f"  - {path}", file=sys.stderr)
    print("Redeploy/restart the server image that contains the current harness parity API surface before running this tier.", file=sys.stderr)
    raise SystemExit(1)
PY
    then
        rm -f "$openapi_tmp"
        return 1
    fi
    rm -f "$openapi_tmp"
}

if [[ -z "${PLAYWRIGHT_WS_URL:-}" ]] && command -v docker >/dev/null 2>&1; then
    browser_ip="$(docker inspect "$HARNESS_PARITY_PLAYWRIGHT_CONTAINER" \
        --format '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null || true)"
    if [[ -n "$browser_ip" ]]; then
        export PLAYWRIGHT_WS_URL="ws://$browser_ip:3000"
        export PLAYWRIGHT_CONNECT_PROTOCOL="${PLAYWRIGHT_CONNECT_PROTOCOL:-cdp}"
    fi
fi

if [[ -z "${SPINDREL_BROWSER_URL:-}" ]] && command -v docker >/dev/null 2>&1; then
    app_ip="$(docker inspect "$HARNESS_PARITY_AGENT_CONTAINER" \
        --format '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null || true)"
    if [[ -n "$app_ip" ]]; then
        export SPINDREL_BROWSER_URL="http://$app_ip:${E2E_PORT}"
        export SPINDREL_BROWSER_API_URL="${SPINDREL_BROWSER_API_URL:-$SPINDREL_BROWSER_URL}"
    fi
fi

echo "=== Harness Live Parity ==="
echo "  Server: ${E2E_HOST}:${E2E_PORT}"
echo "  Tier:   ${HARNESS_PARITY_TIER}"
echo "  Codex:  ${HARNESS_PARITY_CODEX_CHANNEL_ID}"
echo "  Claude: ${HARNESS_PARITY_CLAUDE_CHANNEL_ID}"
echo "  Health bot: ${E2E_BOT_ID}"
echo "  Browser host: ${HARNESS_PARITY_PLAYWRIGHT_HOST}"
echo "  Browser ws: ${PLAYWRIGHT_WS_URL:-<auto/runtime-service/managed>}"
echo "  Browser URL: ${SPINDREL_BROWSER_URL:-<pytest default>}"
echo "  Project path: ${HARNESS_PARITY_PROJECT_PATH}"
echo "  Project timeout: ${HARNESS_PARITY_PROJECT_TIMEOUT}"
echo "  Health wait: ${HARNESS_PARITY_HEALTH_WAIT_TIMEOUT}"
echo ""

PYTEST_BIN=".venv/bin/pytest"
if [[ ! -x "$PYTEST_BIN" ]]; then
    PYTEST_BIN="pytest"
fi

wait_for_server_health
preflight_api_surface

exec "$PYTEST_BIN" tests/e2e/scenarios/test_harness_live_parity.py -q -rs "${PYTEST_ARGS[@]}"
