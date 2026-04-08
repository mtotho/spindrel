#!/usr/bin/env bash
# Scheduled E2E test runner — designed for cron.
# Logs results to ~/logs/e2e/ with timestamps.
# Exits 0 on success, 1 on failure (for cron error mail).
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
# Shared workspace where log-bot can read results
WORKSPACE_SUMMARY="${E2E_WORKSPACE_SUMMARY:-$HOME/.agent-workspaces/shared/70aae325-6b38-47e2-8044-b31064595121/e2e-results.json}"

mkdir -p "$LOG_DIR"

# Load .env for API key
if [[ -z "${E2E_API_KEY:-}" ]] && [[ -f "$PROJECT_ROOT/.env" ]]; then
    E2E_API_KEY=$(grep '^API_KEY=' "$PROJECT_ROOT/.env" | cut -d= -f2)
fi

export E2E_MODE="external"
export E2E_HOST="${E2E_HOST:-localhost}"
export E2E_PORT="${E2E_PORT:-8000}"
export E2E_API_KEY="${E2E_API_KEY:?API key required}"
export E2E_BOT_ID="${E2E_BOT_ID:-e2e}"
export E2E_DEFAULT_MODEL="${E2E_DEFAULT_MODEL:-gemini/gemini-2.5-flash-lite}"
export E2E_REQUEST_TIMEOUT="${E2E_REQUEST_TIMEOUT:-120}"

cd "$PROJECT_ROOT"

{
    echo "=== E2E Scheduled Run: $(date) ==="
    echo "  Server: ${E2E_HOST}:${E2E_PORT}"
    echo "  Bot:    ${E2E_BOT_ID}"
    echo "  Model:  ${E2E_DEFAULT_MODEL}"
    echo ""

    .venv/bin/pytest \
        tests/e2e/scenarios/test_api_contract.py \
        tests/e2e/scenarios/test_regressions.py \
        -v --tb=short 2>&1

    EXIT_CODE=$?

    echo ""
    echo "=== Result: $([ $EXIT_CODE -eq 0 ] && echo 'PASS' || echo 'FAIL') ==="
    echo "=== Finished: $(date) ==="
    echo "=== Exit code: $EXIT_CODE ==="
} > "$LOG_FILE" 2>&1

# Update latest symlink
ln -sf "$LOG_FILE" "$LATEST_LINK"

# Write JSON summary to shared workspace for log-bot to read
_PASSED=$(grep -c "PASSED" "$LOG_FILE" 2>/dev/null || echo 0)
_FAILED=$(grep -c "FAILED" "$LOG_FILE" 2>/dev/null || echo 0)
_ERRORS=$(grep -c "ERROR" "$LOG_FILE" 2>/dev/null || echo 0)
_STATUS="pass"
grep -q "=== Result: FAIL ===" "$LOG_FILE" && _STATUS="fail"
_FAILED_NAMES=$(grep "FAILED" "$LOG_FILE" | sed 's/.*::\(.*\) FAILED.*/\1/' | paste -sd ',' - 2>/dev/null || echo "")
_DURATION=$(grep -oP '\d+\.\d+s' "$LOG_FILE" | tail -1 || echo "?")

cat > "$WORKSPACE_SUMMARY" <<ENDJSON
{
  "timestamp": "$(date -Iseconds)",
  "status": "$_STATUS",
  "passed": $_PASSED,
  "failed": $_FAILED,
  "errors": $_ERRORS,
  "duration": "$_DURATION",
  "failed_tests": "$_FAILED_NAMES",
  "log_file": "$LOG_FILE",
  "model": "${E2E_DEFAULT_MODEL}"
}
ENDJSON

# Prune logs older than 14 days
find "$LOG_DIR" -name "*.log" -mtime +14 -not -name "latest.log" -delete 2>/dev/null

# Print summary unless --quiet
if [[ "${1:-}" != "--quiet" ]]; then
    tail -3 "$LOG_FILE"
fi

# Extract exit code from log (pytest ran in subshell)
if grep -q "=== Result: FAIL ===" "$LOG_FILE"; then
    exit 1
fi
exit 0
