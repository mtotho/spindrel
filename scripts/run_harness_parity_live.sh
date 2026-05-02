#!/usr/bin/env bash
# Run live Codex/Claude harness parity diagnostics against deployed channels.
#
# Defaults target the main live server on localhost:8000 when run on the server.
# Override E2E_HOST/E2E_PORT/E2E_API_KEY for tunnels or other environments.
#
# Usage:
#   ./scripts/run_harness_parity_live.sh
#   ./scripts/run_harness_parity_live.sh --tier bridge
#   ./scripts/run_harness_parity_live.sh --tier project --screenshots auto
#   ./scripts/run_harness_parity_live.sh -k core
#
# Tier list and per-tier required-route preflight live in
# tests/e2e/harness/parity_runner.py — this script delegates to it via
# `python -m tests.e2e.harness.parity_runner ...`.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TIER="${HARNESS_PARITY_TIER:-core}"
PYTEST_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tier)
            TIER="${2:?--tier requires a value (see TIER_ORDER in parity_runner.py)}"
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

PYTHON_BIN=".venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="python3"
    else
        PYTHON_BIN="python"
    fi
fi

run_parity_runner() {
    PYTHONPATH="${PYTHONPATH:-$PROJECT_ROOT}" "$PYTHON_BIN" \
        -m tests.e2e.harness.parity_runner "$@"
}

if [[ "${HARNESS_PARITY_NATIVE_APP:-0}" != "1" && -z "${E2E_API_KEY:-}" ]] && command -v docker >/dev/null 2>&1; then
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
if [[ "${HARNESS_PARITY_NATIVE_APP:-0}" != "1" ]]; then
    export HARNESS_PARITY_AGENT_CONTAINER="${HARNESS_PARITY_AGENT_CONTAINER:-agent-server-agent-server-1}"
fi
export HARNESS_PARITY_PLAYWRIGHT_HOST="${HARNESS_PARITY_PLAYWRIGHT_HOST:-playwright-local}"
export HARNESS_PARITY_PLAYWRIGHT_CONTAINER="${HARNESS_PARITY_PLAYWRIGHT_CONTAINER:-spindrel-local-browser-automation-playwright-1}"
export HARNESS_PARITY_PROJECT_PATH="${HARNESS_PARITY_PROJECT_PATH:-common/projects}"
export HARNESS_PARITY_PROJECT_TIMEOUT="${HARNESS_PARITY_PROJECT_TIMEOUT:-600}"
export HARNESS_PARITY_CAPTURE_SCREENSHOTS="${HARNESS_PARITY_CAPTURE_SCREENSHOTS:-auto}"
export HARNESS_PARITY_SCREENSHOT_OUTPUT_DIR="${HARNESS_PARITY_SCREENSHOT_OUTPUT_DIR:-/tmp/spindrel-harness-live-screenshots}"
export HARNESS_PARITY_SCREENSHOT_ONLY="${HARNESS_PARITY_SCREENSHOT_ONLY:-}"
export HARNESS_PARITY_FAIL_ON_SKIPS="${HARNESS_PARITY_FAIL_ON_SKIPS:-false}"
export HARNESS_PARITY_PYTEST_JUNIT_XML="${HARNESS_PARITY_PYTEST_JUNIT_XML:-}"
# DEFAULT_ALLOWED_SKIP_REGEX is owned by parity_runner.py; bash only overrides
# when the user/env explicitly sets it.
if [[ -n "${HARNESS_PARITY_ALLOWED_SKIP_REGEX:-}" ]]; then
    export HARNESS_PARITY_ALLOWED_SKIP_REGEX
fi

is_local_e2e_host() {
    case "$E2E_HOST" in
        127.*|localhost|0.0.0.0|::1)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

print_local_deploy_diagnostics() {
    if ! is_local_e2e_host || ! command -v docker >/dev/null 2>&1; then
        return 0
    fi
    local container="${HARNESS_PARITY_AGENT_CONTAINER:-}"
    if [[ -z "$container" ]]; then
        return 0
    fi
    if ! docker inspect "$container" >/dev/null 2>&1; then
        return 0
    fi
    echo "Local container diagnostics:" >&2
    docker inspect "$container" \
        --format '  container={{.Name}} image={{.Image}} created={{.Created}} compose_workdir={{index .Config.Labels "com.docker.compose.project.working_dir"}} compose_files={{index .Config.Labels "com.docker.compose.project.config_files"}}' \
        >&2 || true
    local image_id
    image_id="$(docker inspect "$container" --format '{{.Image}}' 2>/dev/null || true)"
    if [[ -n "$image_id" ]]; then
        docker image inspect "$image_id" \
            --format '  image_created={{.Created}} tags={{json .RepoTags}}' \
            >&2 || true
    fi
}

wait_for_server_health() {
    local url="http://${E2E_HOST}:${E2E_PORT}/health"
    local deadline=$((SECONDS + HARNESS_PARITY_HEALTH_WAIT_TIMEOUT))
    while (( SECONDS < deadline )); do
        if command -v curl >/dev/null 2>&1; then
            if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
                return 0
            fi
        else
            if "$PYTHON_BIN" - "$url" <<'PY' >/dev/null 2>&1
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
    local openapi_tmp
    openapi_tmp="$(mktemp)"
    if command -v curl >/dev/null 2>&1; then
        if ! curl -fsS --max-time 10 "$base_url/openapi.json" -o "$openapi_tmp"; then
            echo "Harness parity preflight failed: could not read $base_url/openapi.json" >&2
            rm -f "$openapi_tmp"
            return 1
        fi
    else
        if ! "$PYTHON_BIN" - "$base_url/openapi.json" "$openapi_tmp" <<'PY'
import sys
import urllib.request

with urllib.request.urlopen(sys.argv[1], timeout=10) as resp:
    open(sys.argv[2], "wb").write(resp.read())
PY
        then
            echo "Harness parity preflight failed: could not read $base_url/openapi.json" >&2
            rm -f "$openapi_tmp"
            return 1
        fi
    fi

    if ! run_parity_runner validate-routes \
            --tier "$HARNESS_PARITY_TIER" \
            --openapi-paths-file "$openapi_tmp"; then
        rm -f "$openapi_tmp"
        return 1
    fi
    rm -f "$openapi_tmp"

    local channel_status
    if command -v curl >/dev/null 2>&1; then
        channel_status="$(curl -sS -o /tmp/spindrel-harness-channels-preflight.txt -w '%{http_code}' \
            --max-time 10 \
            -H "Authorization: Bearer ${E2E_API_KEY}" \
            "$base_url/api/v1/admin/channels?page_size=1" 2>/tmp/spindrel-harness-channels-preflight.err || true)"
    else
        channel_status="$("$PYTHON_BIN" - "$base_url" "$E2E_API_KEY" <<'PY' 2>/tmp/spindrel-harness-channels-preflight.err || true
import sys
import urllib.request

req = urllib.request.Request(
    f"{sys.argv[1]}/api/v1/admin/channels?page_size=1",
    headers={"Authorization": f"Bearer {sys.argv[2]}"},
)
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode()
        open("/tmp/spindrel-harness-channels-preflight.txt", "w", encoding="utf-8").write(body)
        print(resp.status)
except Exception as exc:
    open("/tmp/spindrel-harness-channels-preflight.txt", "w", encoding="utf-8").write(str(exc))
    print(getattr(exc, "code", "000"))
PY
)"
    fi

    if [[ "$channel_status" != "200" ]]; then
        echo "Harness parity preflight failed: deployed server cannot list admin channels (HTTP ${channel_status})." >&2
        echo "This usually means the running server image and database schema are out of sync; verify the container was rebuilt from the current repo and migrations are resolvable/applied." >&2
        print_local_deploy_diagnostics
        if [[ -s /tmp/spindrel-harness-channels-preflight.txt ]]; then
            echo "Response body:" >&2
            sed -n '1,12p' /tmp/spindrel-harness-channels-preflight.txt >&2
        fi
        if [[ -s /tmp/spindrel-harness-channels-preflight.err ]]; then
            echo "Request diagnostics:" >&2
            sed -n '1,12p' /tmp/spindrel-harness-channels-preflight.err >&2
        fi
        return 1
    fi
}

if [[ "${HARNESS_PARITY_NATIVE_APP:-0}" != "1" && -z "${PLAYWRIGHT_WS_URL:-}" ]] && is_local_e2e_host && command -v docker >/dev/null 2>&1; then
    browser_ip="$(docker inspect "$HARNESS_PARITY_PLAYWRIGHT_CONTAINER" \
        --format '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null || true)"
    if [[ -n "$browser_ip" ]]; then
        export PLAYWRIGHT_WS_URL="ws://$browser_ip:3000"
        export PLAYWRIGHT_CONNECT_PROTOCOL="${PLAYWRIGHT_CONNECT_PROTOCOL:-cdp}"
    fi
fi

if [[ "${HARNESS_PARITY_NATIVE_APP:-0}" != "1" && -z "${SPINDREL_BROWSER_URL:-}" ]] && is_local_e2e_host && command -v docker >/dev/null 2>&1; then
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
echo "  Capture screenshots: ${HARNESS_PARITY_CAPTURE_SCREENSHOTS}"
echo "  Screenshot only: ${HARNESS_PARITY_SCREENSHOT_ONLY:-<all>}"
echo "  Screenshot output: ${HARNESS_PARITY_SCREENSHOT_OUTPUT_DIR}"
echo "  Fail on skips: ${HARNESS_PARITY_FAIL_ON_SKIPS}"
echo "  Allowed skip regex: ${HARNESS_PARITY_ALLOWED_SKIP_REGEX:-<parity_runner default>}"
echo "  Health wait: ${HARNESS_PARITY_HEALTH_WAIT_TIMEOUT}"
echo ""

wait_for_server_health
preflight_api_surface

LIVE_ARGS=(--tier "$HARNESS_PARITY_TIER")
if [[ -n "$HARNESS_PARITY_PYTEST_JUNIT_XML" ]]; then
    LIVE_ARGS+=(--junit-xml "$HARNESS_PARITY_PYTEST_JUNIT_XML")
fi

set +e
run_parity_runner live "${LIVE_ARGS[@]}" "${PYTEST_ARGS[@]}"
pytest_status=$?
set -e

if [[ "${HARNESS_PARITY_FAIL_ON_SKIPS,,}" =~ ^(1|true|yes)$ ]]; then
    if [[ -z "$HARNESS_PARITY_PYTEST_JUNIT_XML" ]]; then
        echo "HARNESS_PARITY_FAIL_ON_SKIPS requires HARNESS_PARITY_PYTEST_JUNIT_XML" >&2
        exit 1
    fi
    SKIP_ARGS=("$HARNESS_PARITY_PYTEST_JUNIT_XML")
    if [[ -n "${HARNESS_PARITY_ALLOWED_SKIP_REGEX:-}" ]]; then
        SKIP_ARGS+=(--allowed-skip-regex "$HARNESS_PARITY_ALLOWED_SKIP_REGEX")
    fi
    run_parity_runner validate-skips "${SKIP_ARGS[@]}"
fi

if (( pytest_status != 0 )); then
    exit "$pytest_status"
fi

should_capture_screenshots() {
    case "${HARNESS_PARITY_CAPTURE_SCREENSHOTS,,}" in
        1|true|yes|on)
            return 0
            ;;
        0|false|no|off)
            return 1
            ;;
        auto)
            if [[ ${#PYTEST_ARGS[@]} -gt 0 && -z "${HARNESS_PARITY_SCREENSHOT_ONLY:-}" ]]; then
                return 1
            fi
            run_parity_runner tier-at-least "$HARNESS_PARITY_TIER" "project"
            return
            ;;
        *)
            echo "Invalid HARNESS_PARITY_CAPTURE_SCREENSHOTS='$HARNESS_PARITY_CAPTURE_SCREENSHOTS'; use auto, true, or false." >&2
            return 2
            ;;
    esac
}

capture_status=0
should_capture_screenshots || capture_status=$?
if [[ "$capture_status" -eq 2 ]]; then
    exit 2
fi

if [[ "$capture_status" -eq 0 && "${HARNESS_PARITY_SKIP_EXTERNAL_SCREENSHOTS:-false}" != "true" ]]; then
    echo ""
    echo "=== Harness Live Screenshots ==="
    screenshot_args=()
    if [[ -n "$HARNESS_PARITY_SCREENSHOT_ONLY" ]]; then
        screenshot_args+=(--only "$HARNESS_PARITY_SCREENSHOT_ONLY")
    fi
    "$PYTHON_BIN" -m scripts.screenshots.harness_live \
        --api-url "http://${E2E_HOST}:${E2E_PORT}" \
        --ui-url "${SPINDREL_UI_URL:-http://${E2E_HOST}:${E2E_PORT}}" \
        --browser-url "${SPINDREL_BROWSER_URL:-${SPINDREL_UI_URL:-http://${E2E_HOST}:${E2E_PORT}}}" \
        --browser-api-url "${SPINDREL_BROWSER_API_URL:-${SPINDREL_BROWSER_URL:-${SPINDREL_UI_URL:-http://${E2E_HOST}:${E2E_PORT}}}}" \
        --api-key "$E2E_API_KEY" \
        --output-dir "$HARNESS_PARITY_SCREENSHOT_OUTPUT_DIR" \
        "${screenshot_args[@]}"
fi
