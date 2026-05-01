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
DEFAULT_AGENT_E2E_STATE_DIR="$PROJECT_ROOT/scratch/agent-e2e"
NATIVE_ENV="$DEFAULT_AGENT_E2E_STATE_DIR/native-api.env"
HARNESS_ENV="$DEFAULT_AGENT_E2E_STATE_DIR/harness-parity.env"
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

if [[ -n "${SPINDREL_AGENT_E2E_STATE_DIR:-}" ]]; then
    AGENT_STATE_DIR="$PROJECT_ROOT/${SPINDREL_AGENT_E2E_STATE_DIR#./}"
else
    AGENT_STATE_DIR="$DEFAULT_AGENT_E2E_STATE_DIR"
fi
NATIVE_ENV="$AGENT_STATE_DIR/native-api.env"
HARNESS_ENV="$AGENT_STATE_DIR/harness-parity.env"

if [[ -f "$NATIVE_ENV" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$NATIVE_ENV"
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
if [[ "${HARNESS_PARITY_NATIVE_APP:-0}" != "1" ]]; then
    export HARNESS_PARITY_AGENT_CONTAINER="${HARNESS_PARITY_AGENT_CONTAINER:-spindrel-local-e2e-spindrel-1}"
fi
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
    python - <<'PY'
from pathlib import Path
import re
import sys

root = Path.cwd()
guide = root / "docs" / "guides" / "agent-harnesses.md"
if not guide.exists():
    print(f"Missing harness guide: {guide.relative_to(root)}", file=sys.stderr)
    sys.exit(1)

text = guide.read_text(encoding="utf-8", errors="replace")
refs = re.findall(r"!\[[^\]]*\]\(([^)\s]+harness-[^)\s]+\.(?:png|jpg|jpeg|gif|svg|webp))\)", text)
missing = []
for raw in refs:
    resolved = (guide.parent / raw).resolve()
    if not resolved.exists():
        missing.append((raw, resolved))

if missing:
    print("Missing harness screenshot reference(s):", file=sys.stderr)
    for raw, resolved in missing:
        rel = resolved.relative_to(root) if resolved.is_relative_to(root) else resolved
        print(f"  {raw} -> {rel}", file=sys.stderr)
    sys.exit(1)

print(f"Harness guide screenshot refs OK: {len(refs)}")
PY
fi
