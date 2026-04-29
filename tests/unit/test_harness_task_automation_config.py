from types import SimpleNamespace

from app.agent.tasks import _harness_task_turn_overrides
from app.routers.api_v1_admin.tasks import TaskCreateIn, TaskDetailOut, TaskUpdateIn


def test_harness_task_turn_overrides_forward_tools_skills_and_auto_approval():
    overrides = _harness_task_turn_overrides({
        "tools": ["list_channels", "file", "list_channels", ""],
        "skills": ["triage", "code-review", "triage"],
        "skip_tool_approval": True,
    })

    assert overrides == {
        "harness_tool_names": ("list_channels", "file"),
        "harness_skill_ids": ("triage", "code-review"),
        "harness_permission_mode_override": "bypassPermissions",
    }


def test_harness_task_turn_overrides_keep_default_permission_mode_without_skip():
    overrides = _harness_task_turn_overrides({"tools": ["list_channels"]})

    assert overrides["harness_tool_names"] == ("list_channels",)
    assert overrides["harness_skill_ids"] == ()
    assert overrides["harness_permission_mode_override"] is None


def test_task_api_schemas_surface_skip_tool_approval():
    assert "skip_tool_approval" in TaskCreateIn.model_fields
    assert "skip_tool_approval" in TaskUpdateIn.model_fields
    assert "skip_tool_approval" in TaskDetailOut.model_fields


def test_task_detail_surfaces_skip_tool_approval_from_execution_config():
    task = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        status="pending",
        bot_id="codex-bot",
        prompt="run",
        title=None,
        prompt_template_id=None,
        workspace_file_path=None,
        workspace_id=None,
        result=None,
        error=None,
        dispatch_type="none",
        task_type="scheduled",
        recurrence=None,
        client_id=None,
        session_id=None,
        channel_id=None,
        parent_task_id=None,
        run_isolation="inline",
        run_session_id=None,
        session_target=None,
        dispatch_config=None,
        callback_config=None,
        execution_config={"skip_tool_approval": True},
        correlation_id=None,
        delegation_session_id=None,
        trigger_config=None,
        steps=None,
        step_states=None,
        layout={},
        model_override=None,
        model_provider_id_override=None,
        fallback_models=None,
        harness_effort=None,
        trigger_rag_loop=False,
        workflow_id=None,
        workflow_session_mode=None,
        max_run_seconds=None,
        retry_count=0,
        run_count=0,
        source="user",
        subscription_count=0,
        created_at="2026-04-29T00:00:00Z",
        scheduled_at=None,
        run_at=None,
        completed_at=None,
    )

    out = TaskDetailOut.model_validate(task)

    assert out.skip_tool_approval is True
