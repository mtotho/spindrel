from app.agent.task_run_host import _task_run_control_policy


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
