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

Before editing, load the `workspace/project_coding_runs` runtime skill if it is not already loaded.
Before changing files, inspect the workspace state and get latest from the Project's configured development branch when it is safe to do so. Use the Project root as the working directory for file, exec, harness, and screenshot work. If this run is in a fresh Project instance, keep changes inside that instance.
If you are running through a Codex or Claude Code harness, use native tools for repo-local file edits, shell commands, tests, and app/dev server processes. Do not wrap unit tests in Docker, Dockerfile.test, or docker compose. Docker-backed dependencies must use the task-granted Project Dependency Stack tools; do not rely on ambient Docker/socket access from the native shell.
If the Project declares a Dependency Stack, use get_project_dependency_stack and manage_project_dependency_stack for Docker-backed databases/dependencies, logs, restarts, rebuilds, and service commands. Use the returned/injected dependency env in repo-local scripts. Start app/dev servers yourself with native bash on your own unused or assigned port. Do not run raw docker or docker compose in the harness shell, and do not use dependency stacks to run unit tests.

Expected workflow:
1. Understand the bug or feature request and read the relevant code before editing.
2. Call prepare_project_run_handoff(action="prepare_branch") before editing so the Project page records branch readiness.
3. Make focused code changes.
4. Run the smallest relevant tests first with the native Project shell/runtime env, then broaden as needed.
5. For UI changes, run the Project's typecheck/tests, start the project app on the assigned dev target port when present, and capture screenshots against that app. Testing is defined by the Project repo, not by a Spindrel-specific e2e tool.
6. Prepare a review handoff: call prepare_project_run_handoff(action="open_pr") when GitHub credentials and gh are available, or record the blocker from that tool result.
7. Call publish_project_run_receipt before finishing so the Project page has a durable review record. Receipt retries are idempotent when task, handoff, git metadata, or an explicit idempotency_key is stable."""


PROJECT_CODING_RUN_REVIEW_PROMPT = """Review the selected Project coding runs and finalize only accepted work.

Before deciding, load the `workspace/project_coding_runs` runtime skill if it is not already loaded and call get_project_coding_run_review_context for the current review task.
Use the Project root as the working directory. Inspect each selected run's task, receipt, PR, tests, screenshots, and reviewer-visible evidence before making a decision. If the operator asked you to merge accepted PRs, merge only the runs you accept.
If you are running through a Codex or Claude Code harness, use native tools for repo-local inspection, test commands, and app/dev server checks. Do not wrap unit tests in Docker, Dockerfile.test, or docker compose. Docker-backed dependency control, merge/finalizer actions, and receipts must use task-granted Spindrel tools.
If stack-backed dependencies are needed, use get_project_dependency_stack and manage_project_dependency_stack; do not use raw docker or docker compose in the harness shell, and do not use dependency stacks to run unit tests.

Finalization rules:
1. Call get_project_coding_run_review_context before finalizing selected runs.
2. Call finalize_project_coding_run_review once per selected run you have reviewed.
3. Use outcome="accepted" only when the PR/work is ready for the operator's requested merge policy.
4. Use merge=true only when the operator explicitly asked this review session to merge accepted work.
5. Use outcome="rejected" or outcome="blocked" for runs that need changes, have missing evidence, failing checks, or cannot be merged.
6. Only accepted finalizations mark Project coding runs reviewed. Rejected and blocked finalizations leave them available for follow-up work."""


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
class RunPresetHeartbeatDefaults:
    append_spatial_prompt: bool
    append_spatial_map_overview: bool
    include_pinned_widgets: bool
    execution_config: dict[str, Any]
    spatial_policy: dict[str, Any]


@dataclass(frozen=True)
class RunPreset:
    id: str
    title: str
    description: str
    surface: str
    task_defaults: RunPresetTaskDefaults | None = None
    heartbeat_defaults: RunPresetHeartbeatDefaults | None = None


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
            "workspace/project_coding_runs",
            "workspace/files",
            "workspace/member",
        ),
        tools=(
            "file",
            "exec_command",
            "get_project_dependency_stack",
            "manage_project_dependency_stack",
            "prepare_project_run_handoff",
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


PROJECT_CODING_RUN_REVIEW = RunPreset(
    id="project_coding_run_review",
    title="Project Coding Run Review",
    description=(
        "Creates a Project-scoped review task for selected coding runs. The agent can inspect PRs, "
        "merge accepted work when asked, and write durable reviewed provenance."
    ),
    surface="project_coding_run_review",
    task_defaults=RunPresetTaskDefaults(
        title="Project Coding Run Review",
        prompt=PROJECT_CODING_RUN_REVIEW_PROMPT,
        scheduled_at=None,
        recurrence=None,
        task_type="agent",
        trigger_config={"type": "manual"},
        skills=(
            "workspace/project_coding_runs",
            "workspace/files",
            "workspace/member",
        ),
        tools=(
            "file",
            "exec_command",
            "get_project_dependency_stack",
            "manage_project_dependency_stack",
            "prepare_project_run_handoff",
            "get_project_coding_run_review_context",
            "finalize_project_coding_run_review",
        ),
        post_final_to_channel=True,
        history_mode="recent",
        history_recent_count=20,
        skip_tool_approval=True,
        session_target={"mode": "new_each_run"},
        project_instance={"mode": "shared"},
        allow_issue_reporting=True,
        harness_effort="high",
        max_run_seconds=7200,
    ),
)


SPATIAL_WIDGET_STEWARD_HEARTBEAT = RunPreset(
    id="spatial_widget_steward_heartbeat",
    title="Spatial Widget Steward",
    description=(
        "Adds spatial scene inspection, preview, and owned-widget editing to "
        "this channel heartbeat so the bot can curate the channel orbit."
    ),
    surface="channel_heartbeat",
    heartbeat_defaults=RunPresetHeartbeatDefaults(
        append_spatial_prompt=True,
        append_spatial_map_overview=True,
        include_pinned_widgets=True,
        execution_config={
            "skills": (
                "widgets",
                "widgets/channel_dashboards",
                "widgets/spatial_stewardship",
            ),
            "tools": (
                "describe_canvas_neighborhood",
                "view_spatial_canvas",
                "inspect_spatial_widget_scene",
                "preview_spatial_widget_changes",
                "inspect_nearby_spatial_object",
                "pin_spatial_widget",
                "move_spatial_widget",
                "resize_spatial_widget",
                "remove_spatial_widget",
                "assess_widget_usefulness",
                "inspect_widget_pin",
            ),
            "history_mode": "recent",
            "history_recent_count": 30,
            "skip_tool_approval": True,
        },
        spatial_policy={
            "enabled": True,
            "allow_map_view": True,
            "allow_nearby_inspect": True,
            "allow_spatial_widget_management": True,
        },
    ),
)


RUN_PRESETS: tuple[RunPreset, ...] = (
    WIDGET_IMPROVEMENT_HEALTHCHECK,
    PROJECT_CODING_RUN,
    PROJECT_CODING_RUN_REVIEW,
    SPATIAL_WIDGET_STEWARD_HEARTBEAT,
)


def list_run_presets(surface: str | None = None) -> list[RunPreset]:
    if surface is None:
        return list(RUN_PRESETS)
    return [preset for preset in RUN_PRESETS if preset.surface == surface]


def get_run_preset(preset_id: str) -> RunPreset | None:
    return next((preset for preset in RUN_PRESETS if preset.id == preset_id), None)


def serialize_run_preset(preset: RunPreset) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": preset.id,
        "title": preset.title,
        "description": preset.description,
        "surface": preset.surface,
    }
    defaults = preset.task_defaults
    if defaults is not None:
        payload["task_defaults"] = {
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
        }
    hb_defaults = preset.heartbeat_defaults
    if hb_defaults is not None:
        payload["heartbeat_defaults"] = {
            "append_spatial_prompt": hb_defaults.append_spatial_prompt,
            "append_spatial_map_overview": hb_defaults.append_spatial_map_overview,
            "include_pinned_widgets": hb_defaults.include_pinned_widgets,
            "execution_config": {
                **hb_defaults.execution_config,
                "skills": list(hb_defaults.execution_config.get("skills", ())),
                "tools": list(hb_defaults.execution_config.get("tools", ())),
            },
            "spatial_policy": dict(hb_defaults.spatial_policy),
        }
    return payload
