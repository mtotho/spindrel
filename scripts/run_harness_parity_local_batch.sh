#!/usr/bin/env bash
# Run focused local harness parity slices in bounded parallel batches.
#
# Examples:
#   ./scripts/run_harness_parity_local_batch.sh --preset smoke
#   ./scripts/run_harness_parity_local_batch.sh --preset fast --jobs 3
#   ./scripts/run_harness_parity_local_batch.sh --preset slash --dry-run

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PRESET="smoke"
JOBS="${HARNESS_PARITY_LOCAL_BATCH_JOBS:-2}"
PREPARE=true
SCREENSHOTS="off"
DRY_RUN=false
LIST=false
RUN_DIR="$PROJECT_ROOT/scratch/agent-e2e/harness-parity-runs/$(date -u +%Y%m%dT%H%M%SZ)"

usage() {
    cat <<'EOF'
Usage: run_harness_parity_local_batch.sh [options]

Options:
  --preset NAME       smoke, slash, bridge, ui, fast, or deep (default: smoke)
  --jobs N            max parallel slices (default: 2)
  --screenshots MODE  auto, feedback, docs, or off (default: off)
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

declare -a SLICES
case "${PRESET,,}" in
    smoke)
        SLICES=(
            "core|codex and native_slash_direct_commands"
            "core|claude and native_slash_direct_commands"
            "core|codex and core_parity_controls_trace_and_context"
        )
        ;;
    slash)
        SLICES=(
            "core|codex and native_slash_direct_commands"
            "core|claude and native_slash_direct_commands"
            "core|native_command_terminal_handoff"
            "skills|claude_project_local_native_skill_invocation"
        )
        ;;
    bridge)
        SLICES=(
            "bridge|bridge_tool_inventory_and_direct_invocation"
            "writes|bridge_default_mode_mutation_requires_approval"
            "writes|safe_workspace_write_read_delete"
            "memory|memory_explicit_read_uses_bridge"
        )
        ;;
    ui)
        SLICES=(
            "terminal|terminal_tool_output_is_sequential"
            "terminal|mobile_context_panel"
            "replay|persisted_tool_replay_survives_refetch"
        )
        ;;
    fast)
        SLICES=(
            "core|codex and native_slash_direct_commands"
            "core|claude and native_slash_direct_commands"
            "core|codex and core_parity_controls_trace_and_context"
            "core|claude and core_parity_controls_trace_and_context"
            "plan|plan_mode_round_trip"
            "skills|native_image_input_manifest"
            "skills|claude_project_local_native_skill_invocation"
            "replay|persisted_tool_replay_survives_refetch"
        )
        ;;
    deep)
        SLICES=(
            "core|codex and native_slash_direct_commands"
            "core|claude and native_slash_direct_commands"
            "core|core_parity_controls_trace_and_context"
            "bridge|bridge_tool_inventory_and_direct_invocation"
            "terminal|terminal_tool_output_is_sequential"
            "plan|plan_mode_round_trip"
            "writes|safe_workspace_write_read_delete"
            "memory|memory_explicit_read_uses_bridge"
            "skills|native_image_input_manifest"
            "skills|claude_project_local_native_skill_invocation"
            "replay|persisted_tool_replay_survives_refetch"
        )
        ;;
    *)
        echo "Unknown preset '$PRESET'; use smoke, slash, bridge, ui, fast, or deep." >&2
        exit 2
        ;;
esac

if [[ "$LIST" == true ]]; then
    for slice in "${SLICES[@]}"; do
        tier="${slice%%|*}"
        selector="${slice#*|}"
        printf '%-8s %s\n' "$tier" "$selector"
    done
    exit 0
fi

cd "$PROJECT_ROOT"

if [[ "$DRY_RUN" == true ]]; then
    if [[ "$PREPARE" == true ]]; then
        echo "python scripts/agent_e2e_dev.py prepare-harness-parity --skip-setup --no-build"
    fi
    for slice in "${SLICES[@]}"; do
        tier="${slice%%|*}"
        selector="${slice#*|}"
        printf './scripts/run_harness_parity_local.sh --tier %q --screenshots %q -k %q\n' \
            "$tier" "$SCREENSHOTS" "$selector"
    done
    exit 0
fi

mkdir -p "$RUN_DIR"
echo "Harness local batch"
echo "  preset: $PRESET"
echo "  jobs: $JOBS"
echo "  screenshots: $SCREENSHOTS"
echo "  logs: $RUN_DIR"

if [[ "$PREPARE" == true ]]; then
    python scripts/agent_e2e_dev.py prepare-harness-parity --skip-setup --no-build
fi

declare -a PIDS=()
declare -a NAMES=()

run_slice() {
    local index="$1"
    local tier="$2"
    local selector="$3"
    local log_file="$RUN_DIR/${index}-${tier}.log"
    {
        echo "tier=$tier"
        echo "selector=$selector"
        echo
        ./scripts/run_harness_parity_local.sh \
            --tier "$tier" \
            --screenshots "$SCREENSHOTS" \
            -k "$selector"
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
for i in "${!SLICES[@]}"; do
    slice="${SLICES[$i]}"
    tier="${slice%%|*}"
    selector="${slice#*|}"
    name="${tier}: ${selector}"
    run_slice "$((i + 1))" "$tier" "$selector" &
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
