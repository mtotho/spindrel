#!/usr/bin/env bash
# Scheduled E2E test runner — designed for cron.
# Logs results to ~/logs/e2e/ with timestamps.
# Tiered JSON results written by conftest.py pytest hooks.
# Exits 0 on success, 1 on failure (for cron error mail).
#
# By default targets the dedicated E2E instance (port 18000).
# Logs always go to ~/logs/e2e/ regardless of which instance is targeted.
#
# Usage:
#   ./scripts/run_e2e_scheduled.sh           # run and log
#   ./scripts/run_e2e_scheduled.sh --quiet   # suppress stdout (cron default)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$HOME/logs/e2e"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$LOG_DIR/$TIMESTAMP.log"
LATEST_LINK="$LOG_DIR/latest.log"

mkdir -p "$LOG_DIR"

# Default to E2E instance for API key
E2E_INSTANCE_DIR="${E2E_INSTANCE_DIR:-$HOME/spindrel-e2e}"
if [[ -z "${E2E_API_KEY:-}" ]] && [[ -f "$E2E_INSTANCE_DIR/.env" ]]; then
    E2E_API_KEY=$(grep "^API_KEY=" "$E2E_INSTANCE_DIR/.env" | cut -d= -f2)
fi
# Fallback to main instance .env
if [[ -z "${E2E_API_KEY:-}" ]] && [[ -f "$PROJECT_ROOT/.env" ]]; then
    E2E_API_KEY=$(grep "^API_KEY=" "$PROJECT_ROOT/.env" | cut -d= -f2)
fi

export E2E_MODE="external"
export E2E_HOST="${E2E_HOST:-localhost}"
export E2E_PORT="${E2E_PORT:-18000}"
export E2E_API_KEY="${E2E_API_KEY:?API key required}"
export E2E_BOT_ID="${E2E_BOT_ID:-e2e}"
export E2E_DEFAULT_MODEL="${E2E_DEFAULT_MODEL:-gemini-2.5-flash-lite}"
export E2E_REQUEST_TIMEOUT="${E2E_REQUEST_TIMEOUT:-120}"
# E2E_SMOKE_MODELS: JSON array, defaults handled in config.py

cd "$PROJECT_ROOT"

# Enumerate every scenario file under tests/e2e/scenarios/.
# Previous version hard-coded 14 of 24 files, silently dropping
# test_tool_approval_flow / test_workflows / test_chat_* / test_context_discovery /
# test_skill_loading / test_memory_search_depth / test_sessions_plans /
# test_subagents / test_bot_hooks. The fix is one glob.
shopt -s nullglob
SCENARIO_FILES=( tests/e2e/scenarios/test_*.py )
shopt -u nullglob

{
    echo "=== E2E Scheduled Run: $(date) ==="
    echo "  Server:  ${E2E_HOST}:${E2E_PORT}"
    echo "  Bot:     ${E2E_BOT_ID}"
    echo "  Model:   ${E2E_DEFAULT_MODEL}"
    echo "  Files:   ${#SCENARIO_FILES[@]} scenario file(s)"
    echo ""

    .venv/bin/pytest "${SCENARIO_FILES[@]}" -v --tb=short 2>&1

    EXIT_CODE=$?

    echo ""
    echo "=== Result: $([ $EXIT_CODE -eq 0 ] && echo PASS || echo FAIL) ==="
    echo "=== Finished: $(date) ==="
    echo "=== Exit code: $EXIT_CODE ==="
} > "$LOG_FILE" 2>&1

# Update latest symlink
ln -sf "$LOG_FILE" "$LATEST_LINK"

# Prune logs older than 14 days
find "$LOG_DIR" -name "*.log" -mtime +14 -not -name "latest.log" -delete 2>/dev/null
# Prune JSON history older than 90 days
find "$LOG_DIR/e2e-history" -name "*.json" -mtime +90 -delete 2>/dev/null

# Print summary unless --quiet
if [[ "${1:-}" != "--quiet" ]]; then
    tail -3 "$LOG_FILE"
fi
