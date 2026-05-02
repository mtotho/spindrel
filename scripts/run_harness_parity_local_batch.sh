#!/usr/bin/env bash
# Run focused local harness parity slices in bounded parallel batches.
#
# Examples:
#   ./scripts/run_harness_parity_local_batch.sh --preset smoke
#   ./scripts/run_harness_parity_local_batch.sh --preset fast --jobs 3
#   ./scripts/run_harness_parity_local_batch.sh --preset sdk --screenshots docs
#   ./scripts/run_harness_parity_local_batch.sh --preset all --screenshots docs
#
# Slice data (preset → tier+selector list, per-selector screenshot filter)
# lives in tests/e2e/harness/parity_presets.py. This script reads it via
# `python -m tests.e2e.harness.parity_runner expand-slices --preset NAME`.
# The full-suite preset (`all`) is detected via `is-full-suite`.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_ENV="$PROJECT_ROOT/.env.agent-e2e"

if [[ -f "$LOCAL_ENV" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$LOCAL_ENV"
    set +a
fi

if [[ -n "${SPINDREL_AGENT_E2E_STATE_DIR:-}" ]]; then
    AGENT_STATE_DIR="$PROJECT_ROOT/${SPINDREL_AGENT_E2E_STATE_DIR#./}"
else
    AGENT_STATE_DIR="$PROJECT_ROOT/scratch/agent-e2e"
fi

PRESET="smoke"
JOBS="${HARNESS_PARITY_LOCAL_BATCH_JOBS:-2}"
PREPARE=true
SCREENSHOTS="off"
DRY_RUN=false
LIST=false
FAIL_ON_SKIPS=false
RUN_DIR="$AGENT_STATE_DIR/harness-parity-runs/$(date -u +%Y%m%dT%H%M%SZ)"

PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
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

usage() {
    cat <<'EOF'
Usage: run_harness_parity_local_batch.sh [options]

Options:
  --preset NAME       smoke, slash, bridge, sdk, ui, fast, deep, or all (default: smoke)
  --jobs N            max parallel slices (default: 2)
  --screenshots MODE  auto, feedback, docs, or off (default: off)
  --fail-on-skips     fail if pytest reports any skipped tests
  --skip-prepare      do not run prepare-harness-parity first
  --dry-run           print commands without running them
  --list              list slices for the selected preset
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --preset)
            PRESET="${2:?--preset requires a value}"
            shift 2
            ;;
        --preset=*)
            PRESET="${1#--preset=}"
            shift
            ;;
        --jobs)
            JOBS="${2:?--jobs requires a value}"
            shift 2
            ;;
        --jobs=*)
            JOBS="${1#--jobs=}"
            shift
            ;;
        --screenshots)
            SCREENSHOTS="${2:?--screenshots requires auto, feedback, docs, or off}"
            shift 2
            ;;
        --screenshots=*)
            SCREENSHOTS="${1#--screenshots=}"
            shift
            ;;
        --fail-on-skips)
            FAIL_ON_SKIPS=true
            shift
            ;;
        --skip-prepare)
            PREPARE=false
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --list)
            LIST=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if ! [[ "$JOBS" =~ ^[1-9][0-9]*$ ]]; then
    echo "--jobs must be a positive integer" >&2
    exit 2
fi

# Detect full-suite preset (e.g. `all`); strict-mode is auto-enabled.
FULL_SUITE=false
if run_parity_runner is-full-suite --preset "$PRESET" >/dev/null 2>&1; then
    FULL_SUITE=true
    FAIL_ON_SKIPS=true
fi

# Read slice rows (tier|selector|screenshot_filter) from Python.
SLICES_TMP="$(mktemp)"
trap 'rm -f "$SLICES_TMP"' EXIT
if ! run_parity_runner expand-slices --preset "$PRESET" > "$SLICES_TMP" 2>&1; then
    cat "$SLICES_TMP" >&2
    exit 2
fi
mapfile -t SLICE_ROWS < "$SLICES_TMP"

if [[ "$LIST" == true ]]; then
    if [[ "$FULL_SUITE" == true ]]; then
        printf '%-8s %s\n' "replay" "<full suite; no -k selector; fail-on-skips enabled>"
        exit 0
    fi
    for row in "${SLICE_ROWS[@]}"; do
        IFS='|' read -r tier selector _filter <<< "$row"
        printf '%-8s %s\n' "$tier" "$selector"
    done
    exit 0
fi

cd "$PROJECT_ROOT"

format_run_command() {
    local tier="$1"
    local screenshots="$2"
    local selector="$3"
    local screenshot_only="$4"
    local skip_external=false
    if [[ "$screenshot_only" == "__off__" ]]; then
        printf './scripts/run_harness_parity_local.sh --tier %q --screenshots off -k %q\n' \
            "$tier" "$selector"
        return
    fi
    if [[ "$screenshot_only" == __inline__:* ]]; then
        screenshot_only="${screenshot_only#__inline__:}"
        skip_external=true
    fi
    if [[ -n "$screenshot_only" && "$screenshots" != "off" ]]; then
        if [[ "$skip_external" == true ]]; then
            printf 'HARNESS_PARITY_SCREENSHOT_ONLY=%q HARNESS_PARITY_SKIP_EXTERNAL_SCREENSHOTS=true ./scripts/run_harness_parity_local.sh --tier %q --screenshots %q -k %q\n' \
                "$screenshot_only" "$tier" "$screenshots" "$selector"
        else
            printf 'HARNESS_PARITY_SCREENSHOT_ONLY=%q ./scripts/run_harness_parity_local.sh --tier %q --screenshots %q -k %q\n' \
                "$screenshot_only" "$tier" "$screenshots" "$selector"
        fi
    else
        printf './scripts/run_harness_parity_local.sh --tier %q --screenshots %q -k %q\n' \
            "$tier" "$screenshots" "$selector"
    fi
}

if [[ "$DRY_RUN" == true ]]; then
    if [[ "$PREPARE" == true ]]; then
        echo "python scripts/agent_e2e_dev.py prepare-harness-parity"
    fi
    if [[ "$FULL_SUITE" == true ]]; then
        echo "HARNESS_PARITY_FAIL_ON_SKIPS=true HARNESS_PARITY_PYTEST_JUNIT_XML=$RUN_DIR/all-replay.xml ./scripts/run_harness_parity_local.sh --tier replay --screenshots $SCREENSHOTS"
        exit 0
    fi
    for row in "${SLICE_ROWS[@]}"; do
        IFS='|' read -r tier selector filter <<< "$row"
        format_run_command "$tier" "$SCREENSHOTS" "$selector" "$filter"
    done
    exit 0
fi

mkdir -p "$RUN_DIR"
echo "Harness local batch"
echo "  preset: $PRESET"
echo "  jobs: $JOBS"
echo "  screenshots: $SCREENSHOTS"
echo "  fail on skips: $FAIL_ON_SKIPS"
echo "  logs: $RUN_DIR"

if [[ "$PREPARE" == true ]]; then
    python scripts/agent_e2e_dev.py prepare-harness-parity
fi

if [[ "$FULL_SUITE" == true ]]; then
    log_file="$RUN_DIR/all-replay.log"
    export HARNESS_PARITY_FAIL_ON_SKIPS=true
    export HARNESS_PARITY_PYTEST_JUNIT_XML="$RUN_DIR/all-replay.xml"
    {
        echo "tier=replay"
        echo "selector=<full suite>"
        echo "fail_on_skips=true"
        echo
        ./scripts/run_harness_parity_local.sh --tier replay --screenshots "$SCREENSHOTS"
    } >"$log_file" 2>&1
    echo "Harness local all-suite passed. Logs: $RUN_DIR"
    exit 0
fi

declare -a PIDS=()
declare -a NAMES=()

run_slice() {
    local index="$1"
    local tier="$2"
    local selector="$3"
    local screenshot_only="$4"
    local log_file="$RUN_DIR/${index}-${tier}.log"
    {
        echo "tier=$tier"
        echo "selector=$selector"
        if [[ -n "$screenshot_only" && "$SCREENSHOTS" != "off" ]]; then
            echo "screenshot_only=$screenshot_only"
        fi
        echo
        if [[ "$screenshot_only" == "__off__" ]]; then
            HARNESS_PARITY_PYTEST_JUNIT_XML="$RUN_DIR/${index}-${tier}.xml" \
                ./scripts/run_harness_parity_local.sh \
                --tier "$tier" \
                --screenshots off \
                -k "$selector"
        elif [[ -n "$screenshot_only" && "$SCREENSHOTS" != "off" ]]; then
            if [[ "$screenshot_only" == __inline__:* ]]; then
                HARNESS_PARITY_SCREENSHOT_ONLY="${screenshot_only#__inline__:}" \
                    HARNESS_PARITY_SKIP_EXTERNAL_SCREENSHOTS=true \
                    HARNESS_PARITY_PYTEST_JUNIT_XML="$RUN_DIR/${index}-${tier}.xml" \
                    ./scripts/run_harness_parity_local.sh \
                    --tier "$tier" \
                    --screenshots "$SCREENSHOTS" \
                    -k "$selector"
            else
                HARNESS_PARITY_SCREENSHOT_ONLY="$screenshot_only" \
                    HARNESS_PARITY_PYTEST_JUNIT_XML="$RUN_DIR/${index}-${tier}.xml" \
                    ./scripts/run_harness_parity_local.sh \
                    --tier "$tier" \
                    --screenshots "$SCREENSHOTS" \
                    -k "$selector"
            fi
        else
            HARNESS_PARITY_PYTEST_JUNIT_XML="$RUN_DIR/${index}-${tier}.xml" \
                ./scripts/run_harness_parity_local.sh \
                --tier "$tier" \
                --screenshots "$SCREENSHOTS" \
                -k "$selector"
        fi
    } >"$log_file" 2>&1
}

wait_one() {
    local pid="$1"
    local name="$2"
    if wait "$pid"; then
        echo "PASS $name"
        return 0
    fi
    echo "FAIL $name"
    return 1
}

failures=0
export HARNESS_PARITY_FAIL_ON_SKIPS="$FAIL_ON_SKIPS"
for i in "${!SLICE_ROWS[@]}"; do
    IFS='|' read -r tier selector filter <<< "${SLICE_ROWS[$i]}"
    name="${tier}: ${selector}"
    run_slice "$((i + 1))" "$tier" "$selector" "$filter" &
    PIDS+=("$!")
    NAMES+=("$name")
    while (( ${#PIDS[@]} >= JOBS )); do
        if ! wait_one "${PIDS[0]}" "${NAMES[0]}"; then
            failures=$((failures + 1))
        fi
        PIDS=("${PIDS[@]:1}")
        NAMES=("${NAMES[@]:1}")
    done
done

for i in "${!PIDS[@]}"; do
    if ! wait_one "${PIDS[$i]}" "${NAMES[$i]}"; then
        failures=$((failures + 1))
    fi
done

if (( failures > 0 )); then
    echo "Harness local batch failed: $failures slice(s). Logs: $RUN_DIR" >&2
    exit 1
fi

echo "Harness local batch passed. Logs: $RUN_DIR"
