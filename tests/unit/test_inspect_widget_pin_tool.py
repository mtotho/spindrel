"""Unit tests for the inspect_widget_pin bot tool."""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.services import widget_debug
from app.tools.local.inspect_widget_pin import inspect_widget_pin


@pytest.fixture(autouse=True)
def _reset_ring():
    widget_debug.reset_all()
    yield
    widget_debug.reset_all()


@pytest.mark.asyncio
async def test_returns_empty_for_unknown_pin():
    raw = await inspect_widget_pin(str(uuid4()))
    out = json.loads(raw)
    assert out["count"] == 0
    assert out["events"] == []


@pytest.mark.asyncio
async def test_returns_recorded_events():
    pin = uuid4()
    widget_debug.record_event(pin, {
        "kind": "tool-call",
        "tool": "frigate_snapshot",
        "ok": True,
        "response": {"attachment_id": "abc-123"},
    })
    widget_debug.record_event(pin, {
        "kind": "error",
        "message": "TypeError: Cannot read property 'foo' of undefined",
    })
    raw = await inspect_widget_pin(str(pin))
    out = json.loads(raw)
    assert out["count"] == 2
    # Newest first
    assert out["events"][0]["kind"] == "error"
    assert out["events"][1]["kind"] == "tool-call"
    assert out["events"][1]["response"]["attachment_id"] == "abc-123"


@pytest.mark.asyncio
async def test_invalid_pin_returns_error():
    raw = await inspect_widget_pin("not-a-uuid")
    out = json.loads(raw)
    assert "error" in out


@pytest.mark.asyncio
async def test_limit_clamps():
    pin = uuid4()
    for i in range(40):
        widget_debug.record_event(pin, {"kind": "log", "seq": i})
    raw = await inspect_widget_pin(str(pin), limit=5)
    out = json.loads(raw)
    assert out["count"] == 5
    # Limit >50 is clamped to 50
    raw = await inspect_widget_pin(str(pin), limit=999)
    out = json.loads(raw)
    assert out["count"] == 40  # capped by available events
