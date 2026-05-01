#!/usr/bin/env bash
# Run focused local harness parity slices in bounded parallel batches.
#
# Examples:
#   ./scripts/run_harness_parity_local_batch.sh --preset smoke
#   ./scripts/run_harness_parity_local_batch.sh --preset fast --jobs 3
#   ./scripts/run_harness_parity_local_batch.sh --preset sdk --screenshots docs
#   ./scripts/run_harness_parity_local_batch.sh --preset all --screenshots docs

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

declare -a SLICES
FULL_SUITE=false
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
            "core|native_slash_mutating_commands_handoff"
            "skills|claude_project_local_native_skill_invocation"
        )
        ;;
    bridge)
        SLICES=(
            "bridge|bridge_tools_persist_and_renderable"
            "writes|default_mode_bridge_write_approval_resume"
            "writes|safe_workspace_write_read_delete"
            "memory|memory_hint_requires_explicit_read"
        )
        ;;
    sdk)
        SLICES=(
            "core|core_streams_partial_text_before_final"
            "skills|native_image_semantic_reasoning"
            "project|project_instruction_file_discovery"
            "skills|claude and claude_native_todo_progress_persists"
            "skills|claude and claude_native_subagent_persists"
        )
        ;;
    ui)
        SLICES=(
            "terminal|terminal_tool_output_is_sequential"
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
            "core|core_streams_partial_text_before_final"
            "skills|native_image_input_manifest"
            "skills|native_image_semantic_reasoning"
            "skills|claude_project_local_native_skill_invocation"
            "replay|persisted_tool_replay_survives_refetch"
        )
        ;;
    deep)
        SLICES=(
            "core|codex and native_slash_direct_commands"
            "core|claude and native_slash_direct_commands"
            "core|core_parity_controls_trace_and_context"
            "core|core_streams_partial_text_before_final"
            "bridge|bridge_tools_persist_and_renderable"
            "terminal|terminal_tool_output_is_sequential"
            "plan|plan_mode_round_trip"
            "writes|safe_workspace_write_read_delete"
            "memory|memory_hint_requires_explicit_read"
            "skills|native_image_input_manifest"
            "skills|native_image_semantic_reasoning"
            "skills|claude_project_local_native_skill_invocation"
            "project|project_instruction_file_discovery"
            "skills|claude and claude_native_todo_progress_persists"
            "skills|claude and claude_native_subagent_persists"
            "replay|persisted_tool_replay_survives_refetch"
        )
        ;;
    all)
        FULL_SUITE=true
        FAIL_ON_SKIPS=true
        SLICES=("replay|")
        ;;
    *)
        echo "Unknown preset '$PRESET'; use smoke, slash, bridge, sdk, ui, fast, deep, or all." >&2
        exit 2
        ;;
esac

if [[ "$LIST" == true ]]; then
    if [[ "$FULL_SUITE" == true ]]; then
        printf '%-8s %s\n' "replay" "<full suite; no -k selector; fail-on-skips enabled>"
        exit 0
    fi
    for slice in "${SLICES[@]}"; do
        tier="${slice%%|*}"
        selector="${slice#*|}"
        printf '%-8s %s\n' "$tier" "$selector"
    done
    exit 0
fi

cd "$PROJECT_ROOT"

screenshots_for_selector() {
    local selector="$1"
    case "$selector" in
        *bridge_tools_persist_and_renderable*)
            echo "harness-*-bridge-default"
            ;;
        *default_mode_bridge_write_approval_resume*)
            echo "harness-*-terminal-write"
            ;;
        *safe_workspace_write_read_delete*|*memory_hint_requires_explicit_read*|*terminal_tool_output_is_sequential*|*persisted_tool_replay_survives_refetch*)
            echo "__off__"
            ;;
        *core_streams_partial_text_before_final*)
            echo "harness-*-streaming-deltas"
            ;;
        *native_image_semantic_reasoning*)
            echo "harness-*-image-semantic-reasoning"
            ;;
        *project_instruction_file_discovery*)
            echo "harness-*-project-instruction-discovery"
            ;;
        *codex\ and\ native_slash_direct_commands*)
            echo "harness-native-slash-picker-dark,harness-codex-native-plugins-result-dark"
            ;;
        *claude\ and\ native_slash_direct_commands*)
            echo "harness-claude-native-skills-result-dark"
            ;;
        *native_slash_mutating_commands_handoff*)
            echo "harness-codex-native-plugin-install-handoff-dark"
            ;;
        *claude_project_local_native_skill_invocation*)
            echo "harness-claude-native-custom-skill-result-dark"
            ;;
        *claude_native_todo_progress_persists*)
            echo "harness-claude-todowrite-progress"
            ;;
        *claude_native_subagent_persists*)
            echo "harness-claude-native-subagent"
            ;;
        *)
            echo ""
            ;;
    esac
}

format_run_command() {
    local tier="$1"
    local screenshots="$2"
    local selector="$3"
    local screenshot_only="$4"
    if [[ "$screenshot_only" == "__off__" ]]; then
        printf './scripts/run_harness_parity_local.sh --tier %q --screenshots off -k %q\n' \
            "$tier" "$selector"
        return
    fi
    if [[ -n "$screenshot_only" && "$screenshots" != "off" ]]; then
        printf 'HARNESS_PARITY_SCREENSHOT_ONLY=%q ./scripts/run_harness_parity_local.sh --tier %q --screenshots %q -k %q\n' \
            "$screenshot_only" "$tier" "$screenshots" "$selector"
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
    for slice in "${SLICES[@]}"; do
        tier="${slice%%|*}"
        selector="${slice#*|}"
        format_run_command "$tier" "$SCREENSHOTS" "$selector" "$(screenshots_for_selector "$selector")"
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
    local log_file="$RUN_DIR/${index}-${tier}.log"
    local screenshot_only
    screenshot_only="$(screenshots_for_selector "$selector")"
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
            HARNESS_PARITY_SCREENSHOT_ONLY="$screenshot_only" \
                HARNESS_PARITY_PYTEST_JUNIT_XML="$RUN_DIR/${index}-${tier}.xml" \
                ./scripts/run_harness_parity_local.sh \
                --tier "$tier" \
                --screenshots "$SCREENSHOTS" \
                -k "$selector"
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
