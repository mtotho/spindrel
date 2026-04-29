import json
import uuid

import pytest

from app.agent.context import current_bot_id, current_channel_id
from app.tools.local import dashboard_tools


@pytest.mark.asyncio
async def test_pin_widget_stops_at_widget_agency_policy(monkeypatch):
    channel_id = uuid.uuid4()
    token = current_channel_id.set(channel_id)

    async def blocked(_dashboard_key: str) -> str:
        return "Widget changes are proposal-only for this channel."

    async def explode_if_resolved(*args, **kwargs):  # pragma: no cover - should not run
        raise AssertionError("pin_widget should check agency policy before resolving widgets")

    monkeypatch.setattr(dashboard_tools, "_widget_agency_mutation_error", blocked)
    monkeypatch.setattr(dashboard_tools, "_resolve_widget_entry", explode_if_resolved)
    try:
        result = json.loads(await dashboard_tools.pin_widget(widget="weather"))
    finally:
        current_channel_id.reset(token)

    assert result["policy"] == "widget_agency_propose"
    assert "proposal-only" in result["llm"]


@pytest.mark.asyncio
async def test_move_pins_stops_at_widget_agency_policy(monkeypatch):
    channel_id = uuid.uuid4()
    token = current_channel_id.set(channel_id)

    async def blocked(_dashboard_key: str) -> str:
        return "Widget changes are proposal-only for this channel."

    monkeypatch.setattr(dashboard_tools, "_widget_agency_mutation_error", blocked)
    try:
        result = json.loads(await dashboard_tools.move_pins(moves=[{"pin_id": str(uuid.uuid4()), "x": 1}]))
    finally:
        current_channel_id.reset(token)

    assert result["policy"] == "widget_agency_propose"
    assert "proposal-only" in result["error"]


@pytest.mark.asyncio
async def test_move_pins_records_widget_agency_receipt_reason(monkeypatch):
    channel_id = uuid.uuid4()
    pin_id = uuid.uuid4()
    channel_token = current_channel_id.set(channel_id)
    bot_token = current_bot_id.set("bot-widget-fixer")

    class FakeSession:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakePin:
        id = pin_id
        grid_layout = {"x": 0, "y": 0, "w": 1, "h": 6}
        zone = "dock"

    async def allowed(_dashboard_key: str) -> str | None:
        return None

    async def list_pins(_db, *, dashboard_key: str):
        return [FakePin()]

    async def apply_layout_bulk(_db, items, *, dashboard_key: str):
        return {"ok": True, "updated": len(items)}

    async def get_dashboard(_db, _key: str):
        return {"slug": f"channel:{channel_id}", "name": "Widgets", "grid_config": {}}

    def serialize_dashboard(row):
        return row

    def serialize_pin(pin):
        return {
            "id": str(pin.id),
            "display_label": "Dock panel",
            "tool_name": "demo_widget",
            "zone": pin.zone,
            "grid_layout": pin.grid_layout,
        }

    recorded: dict = {}

    async def record_receipt(**kwargs):
        recorded.update(kwargs)
        return "receipt-1", None

    async def enriched_pins(pins):
        return pins

    monkeypatch.setattr(dashboard_tools, "_widget_agency_mutation_error", allowed)
    monkeypatch.setattr(dashboard_tools, "_enriched_pins", enriched_pins)
    monkeypatch.setattr(dashboard_tools, "_render_preview", lambda _dashboard, _pins: "preview")
    monkeypatch.setattr(dashboard_tools, "_record_widget_agency_receipt_safe", record_receipt)
    monkeypatch.setattr("app.db.engine.async_session", lambda: FakeSession())
    monkeypatch.setattr("app.services.dashboard_pins.list_pins", list_pins)
    monkeypatch.setattr("app.services.dashboard_pins.apply_layout_bulk", apply_layout_bulk)
    monkeypatch.setattr("app.services.dashboard_pins.serialize_pin", serialize_pin)
    monkeypatch.setattr("app.services.dashboards.get_dashboard", get_dashboard)
    monkeypatch.setattr("app.services.dashboards.serialize_dashboard", serialize_dashboard)

    try:
        result = json.loads(
            await dashboard_tools.move_pins(
                moves=[{"pin_id": str(pin_id), "zone": "rail"}],
                reason="Dock is hidden in this channel layout.",
            )
        )
    finally:
        current_channel_id.reset(channel_token)
        current_bot_id.reset(bot_token)

    assert result["receipt_id"] == "receipt-1"
    assert recorded["action"] == "move_pins"
    assert recorded["reason"] == "Dock is hidden in this channel layout."
    assert recorded["dashboard_key"] == f"channel:{channel_id}"
    assert recorded["affected_pin_ids"] == [str(pin_id)]
