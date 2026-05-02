from app.services.run_presets import (
    get_run_preset,
    list_run_presets,
    serialize_run_preset,
)


def test_widget_improvement_healthcheck_defaults_to_normal_channel_task_payload():
    preset = get_run_preset("widget_improvement_healthcheck")

    assert preset is not None
    payload = serialize_run_preset(preset)
    defaults = payload["task_defaults"]

    assert payload["surface"] == "channel_task"
    assert defaults["title"] == "Widget Improvement Healthcheck"
    assert defaults["scheduled_at"] == "+1h"
    assert defaults["recurrence"] == "+1w"
    assert defaults["task_type"] == "scheduled"
    assert defaults["trigger_config"] == {"type": "schedule"}
    assert defaults["history_mode"] == "recent"
    assert defaults["history_recent_count"] == 30
    assert defaults["post_final_to_channel"] is True
    assert defaults["skip_tool_approval"] is True
    assert defaults["skills"] == [
        "widgets",
        "widgets/errors",
        "widgets/channel_dashboards",
    ]
    assert defaults["tools"] == [
        "assess_widget_usefulness",
        "describe_dashboard",
        "check_dashboard_widgets",
        "check_widget",
        "inspect_widget_pin",
        "move_pins",
        "unpin_widget",
        "pin_widget",
        "set_dashboard_chrome",
    ]
    assert "Call assess_widget_usefulness" in defaults["prompt"]
    assert "propose_and_fix" in defaults["prompt"]
    assert "No actionable widget fixes." in defaults["prompt"]


def test_list_run_presets_can_filter_by_surface():
    assert [preset.id for preset in list_run_presets("channel_task")] == [
        "widget_improvement_healthcheck"
    ]
    assert [preset.id for preset in list_run_presets("channel_heartbeat")] == [
        "spatial_widget_steward_heartbeat"
    ]
    assert [preset.id for preset in list_run_presets("project_coding_run")] == [
        "project_coding_run"
    ]
    assert [preset.id for preset in list_run_presets("project_coding_run_review")] == [
        "project_coding_run_review"
    ]
    assert list_run_presets("missing_surface") == []


def test_project_coding_run_defaults_to_fresh_project_receipt_flow():
    preset = get_run_preset("project_coding_run")

    assert preset is not None
    payload = serialize_run_preset(preset)
    defaults = payload["task_defaults"]

    assert payload["surface"] == "project_coding_run"
    assert defaults["session_target"] == {"mode": "new_each_run"}
    assert defaults["project_instance"] == {"mode": "fresh"}
    assert defaults["allow_issue_reporting"] is True
    assert defaults["harness_effort"] == "high"
    assert defaults["max_run_seconds"] == 7200
    assert "prepare_project_run_handoff" in defaults["tools"]
    assert "get_project_coding_run_details" in defaults["tools"]
    assert "publish_project_run_receipt" in defaults["tools"]
    assert "run_e2e_tests" not in defaults["tools"]
    assert defaults["skills"] == [
        "project",
        "project/runs/implement",
        "project/runs/loop",
        "workspace/files",
        "workspace/member",
    ]
    assert "prepare_project_run_handoff" in defaults["prompt"]
    assert "publish_project_run_receipt" in defaults["prompt"]
    assert "Testing is defined by the Project repo" in defaults["prompt"]


def test_project_coding_run_review_defaults_to_selected_run_finalizer():
    preset = get_run_preset("project_coding_run_review")

    assert preset is not None
    payload = serialize_run_preset(preset)
    defaults = payload["task_defaults"]

    assert payload["surface"] == "project_coding_run_review"
    assert defaults["session_target"] == {"mode": "new_each_run"}
    assert defaults["project_instance"] == {"mode": "fresh"}
    assert "finalize_project_coding_run_review" in defaults["tools"]
    assert "get_project_coding_run_details" in defaults["tools"]
    assert "get_project_coding_run_review_context" in defaults["tools"]
    assert "prepare_project_run_handoff" in defaults["tools"]
    assert defaults["skills"] == [
        "project",
        "project/runs/review",
        "workspace/files",
        "workspace/member",
    ]
    assert "run_e2e_tests" not in defaults["tools"]
    assert "get_project_coding_run_review_context" in defaults["prompt"]
    assert "Only accepted finalizations mark Project coding runs reviewed" in defaults["prompt"]


def test_unknown_run_preset_returns_none():
    assert get_run_preset("missing") is None


def test_spatial_widget_steward_heartbeat_defaults_to_scene_reasoning_loop():
    preset = get_run_preset("spatial_widget_steward_heartbeat")

    assert preset is not None
    payload = serialize_run_preset(preset)
    defaults = payload["heartbeat_defaults"]

    assert payload["surface"] == "channel_heartbeat"
    assert defaults["append_spatial_prompt"] is True
    assert defaults["append_spatial_map_overview"] is True
    assert defaults["include_pinned_widgets"] is True
    assert "widgets/spatial_stewardship" in defaults["execution_config"]["skills"]
    assert "inspect_spatial_widget_scene" in defaults["execution_config"]["tools"]
    assert "preview_spatial_widget_changes" in defaults["execution_config"]["tools"]
    assert "move_spatial_widget" in defaults["execution_config"]["tools"]
    assert defaults["spatial_policy"]["allow_map_view"] is True
    assert defaults["spatial_policy"]["allow_spatial_widget_management"] is True
