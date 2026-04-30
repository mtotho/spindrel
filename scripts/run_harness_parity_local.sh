#!/usr/bin/env bash
# Run Codex/Claude harness parity diagnostics against the local durable e2e stack.
#
# First prepare the stack/channels:
#   python scripts/agent_e2e_dev.py prepare-harness-parity
#
# Usage mirrors run_harness_parity_live.sh:
#   ./scripts/run_harness_parity_local.sh --tier core
#   ./scripts/run_harness_parity_local.sh --tier skills -k native_image_input_manifest
#   ./scripts/run_harness_parity_local.sh --tier project --screenshots feedback
#   ./scripts/run_harness_parity_local.sh --tier project --screenshots docs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_ENV="$PROJECT_ROOT/.env.agent-e2e"
HARNESS_ENV="$PROJECT_ROOT/scratch/agent-e2e/harness-parity.env"
SCREENSHOTS="auto"
ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --screenshots)
            SCREENSHOTS="${2:?--screenshots requires one of: auto, feedback, docs, off}"
            shift 2
            ;;
        --screenshots=*)
            SCREENSHOTS="${1#--screenshots=}"
            shift
            ;;
        *)
            ARGS+=("$1")
            shift
            ;;
    esac
done

if [[ -f "$LOCAL_ENV" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$LOCAL_ENV"
    set +a
fi

if [[ ! -f "$HARNESS_ENV" ]]; then
    echo "Missing $HARNESS_ENV" >&2
    echo "Run: python scripts/agent_e2e_dev.py prepare-harness-parity" >&2
    exit 1
fi

set -a
# shellcheck disable=SC1090
source "$HARNESS_ENV"
set +a

export E2E_MODE="${E2E_MODE:-external}"
export E2E_HOST="${E2E_HOST:-localhost}"
export E2E_PORT="${E2E_PORT:-18000}"
export E2E_API_KEY="${E2E_API_KEY:-e2e-test-key-12345}"
export E2E_KEEP_RUNNING="${E2E_KEEP_RUNNING:-1}"
export HARNESS_PARITY_LOCAL="${HARNESS_PARITY_LOCAL:-1}"
export HARNESS_PARITY_AGENT_CONTAINER="${HARNESS_PARITY_AGENT_CONTAINER:-spindrel-local-e2e-spindrel-1}"
export SPINDREL_BROWSER_URL="${SPINDREL_BROWSER_URL:-http://localhost:${E2E_PORT}}"
export SPINDREL_BROWSER_API_URL="${SPINDREL_BROWSER_API_URL:-$SPINDREL_BROWSER_URL}"

case "${SCREENSHOTS,,}" in
    auto)
        export HARNESS_PARITY_CAPTURE_SCREENSHOTS="${HARNESS_PARITY_CAPTURE_SCREENSHOTS:-auto}"
        ;;
    feedback)
        export HARNESS_PARITY_CAPTURE_SCREENSHOTS=true
        export HARNESS_PARITY_SCREENSHOT_OUTPUT_DIR="${HARNESS_PARITY_SCREENSHOT_OUTPUT_DIR:-/tmp/spindrel-harness-local-screenshots}"
        ;;
    docs)
        export HARNESS_PARITY_CAPTURE_SCREENSHOTS=true
        export HARNESS_PARITY_SCREENSHOT_OUTPUT_DIR="$PROJECT_ROOT/docs/images"
        ;;
    off|false|no|0)
        export HARNESS_PARITY_CAPTURE_SCREENSHOTS=false
        ;;
    *)
        echo "Invalid --screenshots='$SCREENSHOTS'; use auto, feedback, docs, or off." >&2
        exit 2
        ;;
esac

"$PROJECT_ROOT/scripts/run_harness_parity_live.sh" "${ARGS[@]}"

if [[ "${SCREENSHOTS,,}" == "docs" ]]; then
    cd "$PROJECT_ROOT"
    python -m scripts.screenshots check
fi
