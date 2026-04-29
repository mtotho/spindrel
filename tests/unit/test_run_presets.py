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
    assert "No actionable widget proposals." in defaults["prompt"]


def test_list_run_presets_can_filter_by_surface():
    assert [preset.id for preset in list_run_presets("channel_task")] == [
        "widget_improvement_healthcheck"
    ]
    assert list_run_presets("missing_surface") == []


def test_unknown_run_preset_returns_none():
    assert get_run_preset("missing") is None
