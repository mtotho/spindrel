import json
import uuid

import pytest

from app.agent.context import current_channel_id
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
