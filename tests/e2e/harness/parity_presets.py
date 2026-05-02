"""Slice-preset registry for harness parity batch runs.

Data-only file: each ``Slice`` is a (tier, pytest selector, optional screenshot
filter) triple, and each preset is an ordered tuple of slices. ``run_batch`` in
``parity_runner`` consumes this registry; nothing here imports orchestration so
the architecture guard can pin the no-cycle direction.

The slice content was transcribed byte-equivalent from
``scripts/run_harness_parity_local_batch.sh`` (the ``smoke``/``slash``/...
arrays) and ``screenshots_for_selector``. Adding a preset requires only
extending ``PRESETS``; ``run_batch`` does not need to grow.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Slice:
    """One pytest -k slice for a batch run.

    ``screenshot_filter`` controls per-slice screenshot capture:
    - ``None`` — inherit the batch-wide screenshot mode.
    - ``""`` — same as ``None`` (no override).
    - ``"__off__"`` — force screenshots off for this slice regardless of mode.
    - any other string — pass as ``HARNESS_PARITY_SCREENSHOT_ONLY``.
    """

    tier: str
    selector: str
    screenshot_filter: str | None = None


# Sentinel preset entry meaning "run the full replay tier with no -k selector
# and fail-on-skips enforced." Stored as a Slice with empty selector so the
# preset table stays homogenous.
_FULL_SUITE_REPLAY = Slice(tier="replay", selector="", screenshot_filter=None)


PRESETS: dict[str, tuple[Slice, ...]] = {
    "smoke": (
        Slice("core", "codex and native_slash_direct_commands"),
        Slice("core", "claude and native_slash_direct_commands"),
        Slice("core", "codex and core_parity_controls_trace_and_context"),
    ),
    "slash": (
        Slice("core", "codex and native_slash_direct_commands"),
        Slice("core", "claude and native_slash_direct_commands"),
        Slice("core", "native_slash_mutating_commands_handoff"),
        Slice("skills", "claude_project_local_native_skill_invocation"),
    ),
    "bridge": (
        Slice("bridge", "bridge_tools_persist_and_renderable"),
        Slice("writes", "default_mode_bridge_write_approval_resume"),
        Slice("writes", "safe_workspace_write_read_delete"),
        Slice("memory", "memory_hint_requires_explicit_read"),
    ),
    "sdk": (
        Slice("core", "core_streams_partial_text_before_final"),
        Slice("skills", "native_image_semantic_reasoning"),
        Slice("project", "project_instruction_file_discovery"),
        Slice("skills", "claude and claude_native_todo_progress_persists"),
        Slice("skills", "claude and claude_native_toolsearch_persists"),
        Slice("skills", "claude and claude_native_subagent_persists"),
    ),
    "ui": (
        Slice("terminal", "terminal_tool_output_is_sequential"),
        Slice("replay", "persisted_tool_replay_survives_refetch"),
    ),
    "cli": (
        Slice("terminal", "codex_native_cli_terminal_mirrors_to_spindrel"),
        Slice("terminal", "codex_native_cli_first_turn_promotes_thread_id_and_resumes_chat"),
        Slice("terminal", "codex_native_cli_model_effort_syncs_to_spindrel_composer"),
        Slice("terminal", "claude_native_cli_terminal_mirrors_to_spindrel"),
    ),
    "fast": (
        Slice("core", "codex and native_slash_direct_commands"),
        Slice("core", "claude and native_slash_direct_commands"),
        Slice("core", "codex and core_parity_controls_trace_and_context"),
        Slice("core", "claude and core_parity_controls_trace_and_context"),
        Slice("plan", "plan_mode_round_trip"),
        Slice("core", "core_streams_partial_text_before_final"),
        Slice("skills", "native_image_input_manifest"),
        Slice("skills", "native_image_semantic_reasoning"),
        Slice("skills", "claude_project_local_native_skill_invocation"),
        Slice("replay", "persisted_tool_replay_survives_refetch"),
    ),
    "deep": (
        Slice("core", "codex and native_slash_direct_commands"),
        Slice("core", "claude and native_slash_direct_commands"),
        Slice("core", "core_parity_controls_trace_and_context"),
        Slice("core", "core_streams_partial_text_before_final"),
        Slice("bridge", "bridge_tools_persist_and_renderable"),
        Slice("terminal", "terminal_tool_output_is_sequential"),
        Slice("plan", "plan_mode_round_trip"),
        Slice("writes", "safe_workspace_write_read_delete"),
        Slice("memory", "memory_hint_requires_explicit_read"),
        Slice("skills", "native_image_input_manifest"),
        Slice("skills", "native_image_semantic_reasoning"),
        Slice("skills", "claude_project_local_native_skill_invocation"),
        Slice("project", "project_instruction_file_discovery"),
        Slice("skills", "claude and claude_native_todo_progress_persists"),
        Slice("skills", "claude and claude_native_toolsearch_persists"),
        Slice("skills", "claude and claude_native_subagent_persists"),
        Slice("terminal", "codex_native_cli_terminal_mirrors_to_spindrel"),
        Slice("terminal", "codex_native_cli_model_effort_syncs_to_spindrel_composer"),
        Slice("terminal", "claude_native_cli_terminal_mirrors_to_spindrel"),
        Slice("replay", "persisted_tool_replay_survives_refetch"),
    ),
    "all": (_FULL_SUITE_REPLAY,),
}


# Presets that run the full replay tier with fail-on-skips strict mode rather
# than a list of -k slices.
FULL_SUITE_PRESETS: frozenset[str] = frozenset({"all"})


# Mapping of (selector substring) → screenshot_filter. Order matters: first
# match wins. ``"__off__"`` forces screenshots off regardless of batch mode.
# ``""`` (or absence) means inherit batch mode without filter.
_SELECTOR_SCREENSHOT_RULES: tuple[tuple[str, str], ...] = (
    ("bridge_tools_persist_and_renderable", "harness-*-bridge-default"),
    ("default_mode_bridge_write_approval_resume", "harness-*-terminal-write"),
    ("safe_workspace_write_read_delete", "__off__"),
    ("memory_hint_requires_explicit_read", "__off__"),
    ("terminal_tool_output_is_sequential", "__off__"),
    ("persisted_tool_replay_survives_refetch", "__off__"),
    (
        "core_parity_controls_trace_and_context",
        "harness-codex-native-context-result-dark,harness-claude-native-context-result-dark",
    ),
    ("core_streams_partial_text_before_final", "harness-*-streaming-deltas"),
    ("native_image_semantic_reasoning", "harness-*-image-semantic-reasoning"),
    ("project_instruction_file_discovery", "harness-*-project-instruction-discovery"),
    (
        "codex and native_slash_direct_commands",
        "harness-native-slash-picker-dark,harness-codex-native-plugins-result-dark,harness-codex-native-resume-result-dark,harness-codex-native-agents-result-dark,harness-codex-native-cloud-result-dark,harness-codex-native-approvals-result-dark,harness-codex-native-apps-result-dark,harness-codex-native-skills-result-dark,harness-codex-native-mcp-status-result-dark,harness-codex-native-features-result-dark",
    ),
    (
        "claude and native_slash_direct_commands",
        "harness-claude-native-skills-result-dark,harness-claude-native-agents-result-dark,harness-claude-native-hooks-result-dark,harness-claude-native-status-result-dark,harness-claude-native-doctor-result-dark",
    ),
    (
        "native_slash_mutating_commands_handoff",
        "harness-codex-native-plugin-install-handoff-dark",
    ),
    (
        "claude_project_local_native_skill_invocation",
        "harness-claude-native-custom-skill-result-dark",
    ),
    ("claude_native_todo_progress_persists", "harness-claude-todowrite-progress"),
    ("claude_native_toolsearch_persists", "harness-claude-toolsearch-discovery"),
    ("claude_native_subagent_persists", "harness-claude-native-subagent"),
    (
        "codex_native_cli_terminal_mirrors_to_spindrel",
        "__inline__:harness-codex-native-cli-terminal,harness-codex-native-cli-mirror",
    ),
    (
        "codex_native_cli_model_effort_syncs_to_spindrel_composer",
        "__inline__:harness-codex-native-cli-settings-sync",
    ),
    (
        "claude_native_cli_terminal_mirrors_to_spindrel",
        "__inline__:harness-claude-native-cli-terminal,harness-claude-native-cli-mirror",
    ),
)


def screenshot_filter_for_selector(selector: str) -> str:
    """Return the ``HARNESS_PARITY_SCREENSHOT_ONLY`` value for ``selector``.

    Mirrors ``screenshots_for_selector`` in
    ``scripts/run_harness_parity_local_batch.sh``. Returns ``""`` when the
    selector has no screenshot mapping (inherit batch-wide mode); returns
    ``"__off__"`` when screenshots should be force-disabled for this slice.
    """
    for needle, filter_value in _SELECTOR_SCREENSHOT_RULES:
        if needle in selector:
            return filter_value
    return ""


__all__ = [
    "Slice",
    "PRESETS",
    "FULL_SUITE_PRESETS",
    "screenshot_filter_for_selector",
]
