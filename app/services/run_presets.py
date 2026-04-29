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
   - propose: return concise proposals only.
   - propose_and_fix: apply safe dashboard fixes with the dashboard tools, then explain what changed and why.

Look for actionable issues:
- broken, stale, or low-signal widgets
- duplicate widgets or widgets that overlap in purpose
- hidden layout issues across spatial, dashboard, and chat sidebar surfaces
- missing coverage where a widget would make the channel easier to operate
- places where existing widgets could be clearer, smaller, or more task-focused

Return concise proposals with concrete next actions. If there are no actionable proposals, say: No actionable widget proposals.

Safe fixes in propose_and_fix mode are limited to dashboard operations: move/resize pins, change zones, remove obvious duplicates, pin clearly identified existing widgets, and adjust dashboard chrome. Do not rewrite widget source code in this task."""


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


RUN_PRESETS: tuple[RunPreset, ...] = (WIDGET_IMPROVEMENT_HEALTHCHECK,)


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
        },
    }
