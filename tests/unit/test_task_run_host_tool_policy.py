from types import SimpleNamespace

from app.agent.task_run_host import (
    _history_turns_for_task,
    _metadata_context_visibility,
    _task_context_profile_name,
    _task_run_control_policy,
    _task_run_origin,
)


def test_execution_config_tools_merge_into_required_tools():
    policy = _task_run_control_policy({
        "tools": ["file", "arr_heartbeat_snapshot"],
        "run_control_policy": {
            "tool_surface": "focused_escape",
            "required_tools": ["report_issue", "file"],
        },
    })

    assert policy == {
        "tool_surface": "focused_escape",
        "required_tools": ["report_issue", "file", "arr_heartbeat_snapshot"],
    }


def test_empty_task_run_control_policy_stays_none():
    assert _task_run_control_policy({}) is None


def test_empty_heartbeat_issue_reporting_gets_tight_loop_cap():
    policy = _task_run_control_policy({
        "allow_issue_reporting": True,
        "heartbeat": {"heartbeat_id": "hb-1"},
        "run_control_policy": {
            "hard_max_llm_calls": 30,
            "soft_max_llm_calls": 12,
        },
    })

    assert policy["hard_max_llm_calls"] == 2
    assert policy["soft_max_llm_calls"] == 1


def test_configured_heartbeat_tools_keep_existing_loop_policy():
    policy = _task_run_control_policy({
        "allow_issue_reporting": True,
        "tools": ["arr_heartbeat_snapshot"],
        "heartbeat": {"heartbeat_id": "hb-1"},
        "run_control_policy": {
            "hard_max_llm_calls": 30,
            "soft_max_llm_calls": 12,
        },
    })

    assert policy["required_tools"] == ["arr_heartbeat_snapshot"]
    assert policy["hard_max_llm_calls"] == 30
    assert policy["soft_max_llm_calls"] == 12


def test_api_task_uses_native_chat_context_profile():
    task = SimpleNamespace(task_type="api", execution_config={})
    channel = SimpleNamespace(config={"native_context_policy": "standard"})

    assert _task_context_profile_name(task, channel) == "chat_standard"
    assert _task_run_origin(task) == "chat"


def test_unknown_task_uses_bounded_task_recent_profile():
    task = SimpleNamespace(task_type="agent", execution_config={})
    deps = SimpleNamespace(settings=SimpleNamespace(HEARTBEAT_MAX_HISTORY_TURNS=99))

    assert _task_context_profile_name(task, None) == "task_recent"
    assert _history_turns_for_task(task, "task_recent", deps) == 4


def test_background_task_visibility_metadata_policy():
    assert _metadata_context_visibility("heartbeat") == "background"
    assert _metadata_context_visibility("memory_hygiene") == "background"
    assert _metadata_context_visibility("api") == "chat"
    assert _metadata_context_visibility("agent", is_scheduled=True) == "background"
