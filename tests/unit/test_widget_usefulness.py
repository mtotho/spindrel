from __future__ import annotations

import uuid

import pytest

from app.db.models import Channel
from app.services.dashboard_pins import create_pin, list_pins
from app.services.widget_usefulness import (
    apply_channel_widget_usefulness_proposal,
    assess_channel_widget_usefulness,
    assess_widget_usefulness_from_data,
)


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

    assert result["status"] == "healthy"
    assert result["project_scope_available"] is True
    assert result["recommendations"] == []
    assert result["findings"][0]["type"] == "missing_coverage"
    assert "Project-bound channel" in result["findings"][0]["reason"]


def test_health_findings_are_high_priority() -> None:
    pin = _pin("Broken", pin_id="pin-1")
    result = _assess(
        [pin],
        widget_health={"pin-1": {"status": "failing", "summary": "Browser error"}},
    )

    first = result["findings"][0]
    assert first["type"] == "health"
    assert first["severity"] == "high"
    assert first["pin_id"] == "pin-1"
    assert result["status"] == "healthy"


def test_duplicate_pins_are_reported_once() -> None:
    pins = [
        _pin("Weather", pin_id="a", widget_config={"city": "Detroit"}),
        _pin("Weather", pin_id="b", widget_config={"city": "Detroit"}),
    ]

    result = _assess(pins)

    duplicate_recs = [item for item in result["recommendations"] if item["type"] == "duplicate"]
    assert len(duplicate_recs) == 1
    assert duplicate_recs[0]["requires_policy_decision"] is False
    assert duplicate_recs[0]["evidence"]["pin_ids"] == ["a", "b"]
    assert duplicate_recs[0]["apply"]["action"] == "remove_duplicate_pins"
    assert duplicate_recs[0]["apply"]["keep_pin_id"] == "a"
    assert duplicate_recs[0]["apply"]["remove_pin_ids"] == ["b"]


def test_hidden_chat_zone_is_reported_for_layout_mode() -> None:
    pin = _pin("Dock Panel", pin_id="dock-1", zone="dock")

    result = _assess([pin], channel_config={"layout_mode": "rail-chat"})

    visibility = next(item for item in result["recommendations"] if item["type"] == "visibility")
    assert visibility["surface"] == "chat"
    assert visibility["evidence"]["layout_mode"] == "rail-chat"
    assert visibility["evidence"]["zone"] == "dock"
    assert visibility["apply"]["action"] == "move_pin_to_visible_zone"
    assert visibility["apply"]["to_zone"] == "rail"
    assert result["widget_agency_mode"] == "propose"


def test_widget_agency_mode_surfaces_when_channel_allows_fixes() -> None:
    result = _assess(
        [_pin("Weather", pin_id="weather-1")],
        channel_config={"widget_agency_mode": "propose_and_fix"},
    )

    assert result["widget_agency_mode"] == "propose_and_fix"


def test_context_export_gap_is_reported_when_nothing_reaches_prompt() -> None:
    pin = _pin(
        "Reference",
        context_export={"enabled": True, "summary_kind": "plain_body", "hint_kind": "none"},
    )

    result = _assess(
        [pin],
        context_snapshot={"exported_count": 0, "skipped_count": 1, "rows": []},
    )

    context = next(item for item in result["findings"] if item["type"] == "context")
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

    actionability = next(item for item in result["findings"] if item["type"] == "actionability")
    assert actionability["severity"] == "low"
    assert actionability["evidence"]["action_ids"] == ["add", "toggle"]


def test_no_findings_returns_no_actionable_widget_proposals() -> None:
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
    assert result["summary"] == "No one-click widget fixes available."
    assert result["recommendations"] == []


@pytest.mark.asyncio
async def test_apply_duplicate_widget_proposal_removes_duplicate_pin(db_session) -> None:
    channel_id = uuid.uuid4()
    dashboard_key = f"channel:{channel_id}"
    db_session.add(Channel(id=channel_id, name="Useful Channel", bot_id="bot-1"))
    await db_session.commit()

    keep = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="demo_tool",
        envelope={"display_label": "Weather"},
        dashboard_key=dashboard_key,
        display_label="Weather",
        widget_config={"city": "Detroit"},
    )
    remove = await create_pin(
        db_session,
        source_kind="adhoc",
        tool_name="demo_tool",
        envelope={"display_label": "Weather"},
        dashboard_key=dashboard_key,
        display_label="Weather",
        widget_config={"city": "Detroit"},
    )

    assessment = await assess_channel_widget_usefulness(db_session, channel_id)
    proposal = next(item for item in assessment["recommendations"] if item["type"] == "duplicate")

    result = await apply_channel_widget_usefulness_proposal(
        db_session,
        channel_id,
        proposal_id=proposal["proposal_id"],
    )

    pins = await list_pins(db_session, dashboard_key=dashboard_key)
    pin_ids = {pin.id for pin in pins}
    assert result["ok"] is True
    assert result["action"] == "remove_duplicate_pins"
    assert keep.id in pin_ids
    assert remove.id not in pin_ids
    assert result["receipt"]["action"] == "apply_remove_duplicate_pins"
