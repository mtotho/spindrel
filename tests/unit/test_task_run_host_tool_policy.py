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
