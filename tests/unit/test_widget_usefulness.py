from __future__ import annotations

import uuid

from app.services.widget_usefulness import assess_widget_usefulness_from_data


def _pin(
    label: str,
    *,
    pin_id: str | None = None,
    zone: str = "grid",
    tool_name: str = "demo_tool",
    widget_config: dict | None = None,
    context_export: dict | None = None,
    actions: list[dict] | None = None,
    context_summary: str | None = None,
    context_hint: str | None = None,
) -> dict:
    contract: dict = {}
    if context_export is not None:
        contract["context_export"] = context_export
    if actions is not None:
        contract["actions"] = actions
    pin = {
        "id": pin_id or str(uuid.uuid4()),
        "zone": zone,
        "tool_name": tool_name,
        "tool_args": {},
        "widget_config": widget_config or {},
        "display_label": label,
        "envelope": {"display_label": label},
        "widget_contract": contract,
    }
    if context_summary:
        pin["context_summary"] = context_summary
    if context_hint:
        pin["context_hint"] = context_hint
    return pin


def _assess(pins: list[dict], **overrides):
    return assess_widget_usefulness_from_data(
        channel_id="channel-1",
        channel_name="Useful Channel",
        channel_config=overrides.pop("channel_config", {}),
        pins=pins,
        widget_health=overrides.pop("widget_health", {}),
        context_snapshot=overrides.pop("context_snapshot", None),
        project=overrides.pop("project", None),
    )


def _types(result: dict) -> set[str]:
    return {item["type"] for item in result["recommendations"]}


def test_empty_dashboard_recommends_project_starter_widgets() -> None:
    result = _assess(
        [],
        project={
            "id": "project-1",
            "name": "Project",
            "root_path": "common/projects/demo",
            "attached_channel_count": 2,
        },
    )

    assert result["status"] == "needs_attention"
    assert result["project_scope_available"] is True
    assert result["recommendations"][0]["type"] == "missing_coverage"
    assert "Project-bound channel" in result["recommendations"][0]["reason"]


def test_health_findings_are_high_priority() -> None:
    pin = _pin("Broken", pin_id="pin-1")
    result = _assess(
        [pin],
        widget_health={"pin-1": {"status": "failing", "summary": "Browser error"}},
    )

    first = result["recommendations"][0]
    assert first["type"] == "health"
    assert first["severity"] == "high"
    assert first["pin_id"] == "pin-1"
    assert result["status"] == "action_required"


def test_duplicate_pins_are_reported_once() -> None:
    pins = [
        _pin("Weather", pin_id="a", widget_config={"city": "Detroit"}),
        _pin("Weather", pin_id="b", widget_config={"city": "Detroit"}),
    ]

    result = _assess(pins)

    duplicate_recs = [item for item in result["recommendations"] if item["type"] == "duplicate"]
    assert len(duplicate_recs) == 1
    assert duplicate_recs[0]["requires_policy_decision"] is True
    assert duplicate_recs[0]["evidence"]["pin_ids"] == ["a", "b"]


def test_hidden_chat_zone_is_reported_for_layout_mode() -> None:
    pin = _pin("Dock Panel", pin_id="dock-1", zone="dock")

    result = _assess([pin], channel_config={"layout_mode": "rail-chat"})

    visibility = next(item for item in result["recommendations"] if item["type"] == "visibility")
    assert visibility["surface"] == "chat"
    assert visibility["evidence"]["layout_mode"] == "rail-chat"
    assert visibility["evidence"]["zone"] == "dock"


def test_context_export_gap_is_reported_when_nothing_reaches_prompt() -> None:
    pin = _pin(
        "Reference",
        context_export={"enabled": True, "summary_kind": "plain_body", "hint_kind": "none"},
    )

    result = _assess(
        [pin],
        context_snapshot={"exported_count": 0, "skipped_count": 1, "rows": []},
    )

    context = next(item for item in result["recommendations"] if item["type"] == "context")
    assert context["severity"] == "medium"
    assert context["evidence"]["export_enabled_count"] == 1


def test_actionable_widget_without_hint_is_reported() -> None:
    pin = _pin(
        "Todo",
        actions=[{"id": "add"}, {"id": "toggle"}],
        context_export={"enabled": True, "summary_kind": "plain_body", "hint_kind": "none"},
        context_summary="2 open",
    )

    result = _assess(
        [pin],
        context_snapshot={"exported_count": 1, "skipped_count": 0, "rows": []},
    )

    actionability = next(item for item in result["recommendations"] if item["type"] == "actionability")
    assert actionability["severity"] == "low"
    assert actionability["evidence"]["action_ids"] == ["add", "toggle"]


def test_no_findings_returns_no_actionable_widget_findings() -> None:
    pin = _pin(
        "Notes",
        zone="rail",
        context_export={"enabled": True, "summary_kind": "plain_body", "hint_kind": "none"},
        context_summary="Current note",
    )

    result = _assess(
        [pin],
        context_snapshot={"exported_count": 1, "skipped_count": 0, "rows": []},
    )

    assert result["status"] == "healthy"
    assert result["summary"] == "No actionable widget findings."
    assert result["recommendations"] == []
