"""Internal run preset registry.

Run presets are not persisted primitives. They are canned task-create payloads
that let product surfaces offer one-click setup while still creating ordinary
tasks underneath.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


WIDGET_IMPROVEMENT_PROMPT = """Improve this channel dashboard's widgets for usefulness and health.

Use the widget inspection tools to understand the current dashboard before proposing or changing anything:
1. Call assess_widget_usefulness for this channel.
2. Call describe_dashboard only when you need raw pin/layout detail beyond the assessment.
3. Call check_dashboard_widgets only when the assessment points to health/runtime concerns.
4. Use check_widget or inspect_widget_pin when a specific widget or pin needs deeper inspection.
5. Read widget_agency_mode from the assessment:
   - propose: return concise widget fix suggestions only; do not mutate the dashboard.
   - propose_and_fix: apply safe dashboard fixes with the dashboard tools. Pass a concise `reason` to each mutating dashboard tool so the bot widget change receipt explains why it changed.

Look for actionable issues:
- broken, stale, or low-signal widgets
- duplicate widgets or widgets that overlap in purpose
- hidden layout issues across spatial, dashboard, and chat sidebar surfaces
- missing coverage where a widget would make the channel easier to operate
- places where existing widgets could be clearer, smaller, or more task-focused

Return concise widget fix suggestions with concrete next actions. Treat `recommendations` as one-click fixes and keep advisory-only `findings` clearly separate. If there are no actionable widget fixes, say: No actionable widget fixes.

Safe fixes in propose_and_fix mode are limited to dashboard operations: move/resize pins, change zones, remove obvious duplicates, pin clearly identified existing widgets, and adjust dashboard chrome. Do not rewrite widget source code in this task."""


PROJECT_CODING_RUN_PROMPT = """Implement the requested Project task in this Project workspace.

Before changing files, inspect the workspace state and get latest from the Project's configured development branch when it is safe to do so. Use the Project root as the working directory for file, exec, harness, and screenshot work. If this run is in a fresh Project instance, keep changes inside that instance.

Expected workflow:
1. Understand the bug or feature request and read the relevant code before editing.
2. Make focused code changes.
3. Run the smallest relevant tests first, then broaden as needed.
4. For UI changes, run the Project's typecheck and capture screenshots against the e2e-testing server when available.
5. Prepare a review handoff: branch, changed files, tests, screenshots, and any blocker.
6. Call publish_project_run_receipt before finishing so the Project page has a durable review record."""


@dataclass(frozen=True)
class RunPresetTaskDefaults:
    title: str
    prompt: str
    scheduled_at: str | None
    recurrence: str | None
    task_type: str
    trigger_config: dict[str, Any]
    skills: tuple[str, ...]
    tools: tuple[str, ...]
    post_final_to_channel: bool
    history_mode: str
    history_recent_count: int
    skip_tool_approval: bool
    session_target: dict[str, Any] | None = None
    project_instance: dict[str, Any] | None = None
    allow_issue_reporting: bool | None = None
    harness_effort: str | None = None
    max_run_seconds: int | None = None


@dataclass(frozen=True)
class RunPreset:
    id: str
    title: str
    description: str
    surface: str
    task_defaults: RunPresetTaskDefaults


WIDGET_IMPROVEMENT_HEALTHCHECK = RunPreset(
    id="widget_improvement_healthcheck",
    title="Widget Improvement Healthcheck",
    description=(
        "Schedules a recurring review of this channel's dashboard widgets, "
        "including usefulness, health, stale widgets, and hidden layout issues."
    ),
    surface="channel_task",
    task_defaults=RunPresetTaskDefaults(
        title="Widget Improvement Healthcheck",
        prompt=WIDGET_IMPROVEMENT_PROMPT,
        scheduled_at="+1h",
        recurrence="+1w",
        task_type="scheduled",
        trigger_config={"type": "schedule"},
        skills=("widgets", "widgets/errors", "widgets/channel_dashboards"),
        tools=(
            "assess_widget_usefulness",
            "describe_dashboard",
            "check_dashboard_widgets",
            "check_widget",
            "inspect_widget_pin",
            "move_pins",
            "unpin_widget",
            "pin_widget",
            "set_dashboard_chrome",
        ),
        post_final_to_channel=True,
        history_mode="recent",
        history_recent_count=30,
        skip_tool_approval=True,
    ),
)


PROJECT_CODING_RUN = RunPreset(
    id="project_coding_run",
    title="Agent Coding Run",
    description=(
        "Creates a Project-scoped implementation run with a fresh Project instance, "
        "exec/file/screenshot tools, and a required review receipt."
    ),
    surface="project_coding_run",
    task_defaults=RunPresetTaskDefaults(
        title="Project Coding Run",
        prompt=PROJECT_CODING_RUN_PROMPT,
        scheduled_at=None,
        recurrence=None,
        task_type="agent",
        trigger_config={"type": "manual"},
        skills=(
            "spindrel-visual-feedback-loop",
            "impeccable",
        ),
        tools=(
            "file",
            "exec_command",
            "run_e2e_tests",
            "publish_project_run_receipt",
        ),
        post_final_to_channel=True,
        history_mode="recent",
        history_recent_count=20,
        skip_tool_approval=True,
        session_target={"mode": "new_each_run"},
        project_instance={"mode": "fresh"},
        allow_issue_reporting=True,
        harness_effort="high",
        max_run_seconds=7200,
    ),
)


RUN_PRESETS: tuple[RunPreset, ...] = (WIDGET_IMPROVEMENT_HEALTHCHECK, PROJECT_CODING_RUN)


def list_run_presets(surface: str | None = None) -> list[RunPreset]:
    if surface is None:
        return list(RUN_PRESETS)
    return [preset for preset in RUN_PRESETS if preset.surface == surface]


def get_run_preset(preset_id: str) -> RunPreset | None:
    return next((preset for preset in RUN_PRESETS if preset.id == preset_id), None)


def serialize_run_preset(preset: RunPreset) -> dict[str, Any]:
    defaults = preset.task_defaults
    return {
        "id": preset.id,
        "title": preset.title,
        "description": preset.description,
        "surface": preset.surface,
        "task_defaults": {
            "title": defaults.title,
            "prompt": defaults.prompt,
            "scheduled_at": defaults.scheduled_at,
            "recurrence": defaults.recurrence,
            "task_type": defaults.task_type,
            "trigger_config": dict(defaults.trigger_config),
            "skills": list(defaults.skills),
            "tools": list(defaults.tools),
            "post_final_to_channel": defaults.post_final_to_channel,
            "history_mode": defaults.history_mode,
            "history_recent_count": defaults.history_recent_count,
            "skip_tool_approval": defaults.skip_tool_approval,
            "session_target": dict(defaults.session_target) if defaults.session_target is not None else None,
            "project_instance": dict(defaults.project_instance) if defaults.project_instance is not None else None,
            "allow_issue_reporting": defaults.allow_issue_reporting,
            "harness_effort": defaults.harness_effort,
            "max_run_seconds": defaults.max_run_seconds,
        },
    }
