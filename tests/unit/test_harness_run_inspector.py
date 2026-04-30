from types import SimpleNamespace

from app.routers.api_v1_sessions import _build_harness_run_inspector


def test_harness_run_inspector_condenses_last_turn_metadata():
    inspector = _build_harness_run_inspector(
        runtime="codex",
        harness_meta={
            "session_id": "thread-1",
            "effective_cwd": "/workspace/project",
            "codex_latency_ms": {"thread_start_ms": 50, "first_text_ms": 120},
            "codex_dynamic_tools": ["list_channels", "get_tool_info"],
            "codex_thread_restart_reason": "cwd_changed",
            "input_manifest": {
                "attachments": [{"kind": "image"}],
                "workspace_uploads": [{"path": ".uploads/a.png"}],
                "tagged_skill_ids": ["triage"],
                "runtime_items": [{"type": "image"}],
                "runtime_item_counts": {"image": 1},
                "warnings": ["large attachment omitted"],
            },
        },
        settings=SimpleNamespace(model="gpt-5.4-mini", effort="low"),
        permission_mode="default",
        session_plan_mode="chat",
        last_turn_at="2026-04-30T12:00:00+00:00",
        workdir="/workspace/project",
        workdir_source="project",
        bridge_status={
            "status": "ready",
            "exported_tools": ["list_channels"],
            "inventory_errors": ["mcp unavailable"],
            "missing_baseline_tools": ["read_conversation_history"],
        },
    )

    assert inspector["runtime"] == "codex"
    assert inspector["native_session_id"] == "thread-1"
    assert inspector["cwd"] == "/workspace/project"
    assert inspector["model"] == "gpt-5.4-mini"
    assert inspector["latency_ms"]["first_text_ms"] == 120
    assert inspector["input_manifest"]["attachment_count"] == 1
    assert inspector["input_manifest"]["runtime_item_counts"] == {"image": 1}
    assert inspector["bridge"]["exported_tool_count"] == 1
    assert inspector["bridge"]["inventory_error_count"] == 1
    assert inspector["native_inventory"]["codex_dynamic_tools"] == [
        "list_channels",
        "get_tool_info",
    ]
    assert inspector["native_inventory"]["codex_thread_restart_reason"] == "cwd_changed"


def test_harness_run_inspector_counts_claude_slash_inventory():
    inspector = _build_harness_run_inspector(
        runtime="claude-code",
        harness_meta={
            "session_id": "claude-session",
            "claude_native_slash_commands": [
                {"name": "skills"},
                {"name": "project-local"},
            ],
        },
        settings=SimpleNamespace(model=None, effort=None),
        permission_mode="acceptEdits",
        session_plan_mode="planning",
        last_turn_at=None,
        workdir="/workspace/project",
        workdir_source="project",
        bridge_status={},
    )

    assert inspector["native_inventory"]["claude_slash_command_count"] == 2
    assert inspector["native_inventory"]["claude_slash_commands"][1]["name"] == "project-local"
    assert inspector["session_plan_mode"] == "planning"
    assert inspector["permission_mode"] == "acceptEdits"
