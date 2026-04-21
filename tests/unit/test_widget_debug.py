"""Unit tests for the widget debug event ring store."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.services import widget_debug


@pytest.fixture(autouse=True)
def _reset_ring():
    widget_debug.reset_all()
    yield
    widget_debug.reset_all()


def test_record_and_read_single_event():
    pin = uuid4()
    widget_debug.record_event(pin, {"kind": "tool-call", "tool": "x", "ok": True})
    events = widget_debug.get_events(pin)
    assert len(events) == 1
    assert events[0]["kind"] == "tool-call"
    assert events[0]["tool"] == "x"
    assert "ts_server" in events[0]


def test_newest_first_ordering():
    pin = uuid4()
    for i in range(5):
        widget_debug.record_event(pin, {"kind": "log", "seq": i})
    events = widget_debug.get_events(pin)
    assert [e["seq"] for e in events] == [4, 3, 2, 1, 0]


def test_ring_cap_drops_oldest():
    pin = uuid4()
    cap = widget_debug.MAX_EVENTS_PER_PIN
    for i in range(cap + 10):
        widget_debug.record_event(pin, {"kind": "log", "seq": i})
    events = widget_debug.get_events(pin, limit=cap + 10)
    # Ring caps at MAX_EVENTS_PER_PIN, oldest dropped.
    assert len(events) == cap
    # Newest first: seq=cap+9 at index 0.
    assert events[0]["seq"] == cap + 9
    # Oldest preserved: seq=10 at the tail (since 0..9 were evicted).
    assert events[-1]["seq"] == 10


def test_limit_bounds_result():
    pin = uuid4()
    for i in range(20):
        widget_debug.record_event(pin, {"kind": "log", "seq": i})
    events = widget_debug.get_events(pin, limit=5)
    assert len(events) == 5
    assert [e["seq"] for e in events] == [19, 18, 17, 16, 15]


def test_per_pin_isolation():
    pin_a = uuid4()
    pin_b = uuid4()
    widget_debug.record_event(pin_a, {"kind": "log", "who": "a"})
    widget_debug.record_event(pin_b, {"kind": "log", "who": "b"})
    events_a = widget_debug.get_events(pin_a)
    events_b = widget_debug.get_events(pin_b)
    assert len(events_a) == 1 and events_a[0]["who"] == "a"
    assert len(events_b) == 1 and events_b[0]["who"] == "b"


def test_get_events_unknown_pin():
    assert widget_debug.get_events(uuid4()) == []


def test_clear_events():
    pin = uuid4()
    for i in range(3):
        widget_debug.record_event(pin, {"kind": "log", "seq": i})
    removed = widget_debug.clear_events(pin)
    assert removed == 3
    assert widget_debug.get_events(pin) == []


def test_clear_unknown_pin_returns_zero():
    assert widget_debug.clear_events(uuid4()) == 0


def test_zero_limit_returns_empty():
    pin = uuid4()
    widget_debug.record_event(pin, {"kind": "log"})
    assert widget_debug.get_events(pin, limit=0) == []
