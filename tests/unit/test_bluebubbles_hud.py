"""Tests for BlueBubbles HUD echo diagnostics data logic."""
import time

import pytest

from integrations.bluebubbles.echo_tracker import (
    EchoTracker,
    _CIRCUIT_BREAKER_MAX,
    _CIRCUIT_BREAKER_WINDOW,
    _ECHO_SUPPRESS_WINDOW,
    _REPLY_COOLDOWN,
)


def _build_diagnostics(tracker: EchoTracker, paused: bool = False) -> dict:
    """Replicate the diagnostic data logic from the /hud/echo-diagnostics endpoint.

    This avoids importing the full router (which needs FastAPI/DB deps) and
    tests the pure data-assembly logic that the endpoint relies on.
    """
    now = time.time()
    items: list[dict] = []

    all_guids = set(tracker._chat_replies.keys()) | set(tracker._sent_content.keys())

    circuit_open_count = 0
    suppress_active_count = 0
    for chat_guid in all_guids:
        replies = tracker._chat_replies.get(chat_guid, [])
        recent = [ts for ts in replies if now - ts < _CIRCUIT_BREAKER_WINDOW]
        if len(recent) >= _CIRCUIT_BREAKER_MAX:
            circuit_open_count += 1
        if any(now - ts < _ECHO_SUPPRESS_WINDOW for ts in replies):
            suppress_active_count += 1

    items.append({
        "type": "badge",
        "label": "Webhooks",
        "value": "Paused" if paused else "Active",
        "variant": "warning" if paused else "success",
    })
    items.append({
        "type": "badge",
        "label": "Tracked Chats",
        "value": str(len(all_guids)),
        "variant": "muted" if len(all_guids) == 0 else "accent",
    })
    if circuit_open_count > 0:
        items.append({
            "type": "badge",
            "label": "Circuit Breakers",
            "value": f"{circuit_open_count} open",
            "variant": "danger",
        })
    if suppress_active_count > 0:
        items.append({
            "type": "badge",
            "label": "Suppress Windows",
            "value": f"{suppress_active_count} active",
            "variant": "warning",
        })

    return {
        "visible": True,
        "items": items,
        "tracked_chats": len(all_guids),
        "circuit_open_count": circuit_open_count,
        "suppress_active_count": suppress_active_count,
    }


class TestEmptyTracker:
    """Diagnostics with no tracked state."""

    def test_empty_tracker_shows_zero_chats(self):
        tracker = EchoTracker()
        result = _build_diagnostics(tracker)
        assert result["tracked_chats"] == 0
        assert result["circuit_open_count"] == 0
        assert result["suppress_active_count"] == 0

    def test_empty_tracker_active_badge(self):
        tracker = EchoTracker()
        result = _build_diagnostics(tracker)
        webhooks_badge = result["items"][0]
        assert webhooks_badge["label"] == "Webhooks"
        assert webhooks_badge["value"] == "Active"
        assert webhooks_badge["variant"] == "success"

    def test_empty_tracker_paused_badge(self):
        tracker = EchoTracker()
        result = _build_diagnostics(tracker, paused=True)
        webhooks_badge = result["items"][0]
        assert webhooks_badge["value"] == "Paused"
        assert webhooks_badge["variant"] == "warning"

    def test_empty_tracker_muted_chat_count(self):
        tracker = EchoTracker()
        result = _build_diagnostics(tracker)
        chat_badge = result["items"][1]
        assert chat_badge["label"] == "Tracked Chats"
        assert chat_badge["value"] == "0"
        assert chat_badge["variant"] == "muted"


class TestActiveChats:
    """Diagnostics with active chat tracking."""

    def test_single_chat_appears(self):
        tracker = EchoTracker()
        tracker.track_sent("t1", "hello", chat_guid="chat-A")
        result = _build_diagnostics(tracker)
        assert result["tracked_chats"] == 1

    def test_multiple_chats_counted(self):
        tracker = EchoTracker()
        tracker.track_sent("t1", "hello", chat_guid="chat-A")
        tracker.track_sent("t2", "world", chat_guid="chat-B")
        tracker.track_sent("t3", "test", chat_guid="chat-C")
        result = _build_diagnostics(tracker)
        assert result["tracked_chats"] == 3

    def test_chat_count_badge_accent(self):
        tracker = EchoTracker()
        tracker.track_sent("t1", "hello", chat_guid="chat-A")
        result = _build_diagnostics(tracker)
        chat_badge = result["items"][1]
        assert chat_badge["value"] == "1"
        assert chat_badge["variant"] == "accent"


class TestCircuitBreakerDiagnostics:
    """Circuit breaker detection in diagnostics."""

    def test_no_circuit_breaker_when_under_limit(self):
        tracker = EchoTracker()
        for i in range(_CIRCUIT_BREAKER_MAX - 1):
            tracker.track_sent(f"t{i}", f"msg{i}", chat_guid="chat-A")
        result = _build_diagnostics(tracker)
        assert result["circuit_open_count"] == 0
        # No circuit breaker badge should be in items
        labels = [item.get("label") for item in result["items"]]
        assert "Circuit Breakers" not in labels

    def test_circuit_breaker_detected(self):
        tracker = EchoTracker()
        for i in range(_CIRCUIT_BREAKER_MAX):
            tracker.track_sent(f"t{i}", f"msg{i}", chat_guid="chat-A")
        result = _build_diagnostics(tracker)
        assert result["circuit_open_count"] == 1
        # Circuit breaker badge should be present
        cb_badges = [item for item in result["items"] if item.get("label") == "Circuit Breakers"]
        assert len(cb_badges) == 1
        assert cb_badges[0]["variant"] == "danger"
        assert "1 open" in cb_badges[0]["value"]

    def test_multiple_circuit_breakers(self):
        tracker = EchoTracker()
        for chat in ("chat-A", "chat-B"):
            for i in range(_CIRCUIT_BREAKER_MAX):
                tracker.track_sent(f"t-{chat}-{i}", f"msg{i}", chat_guid=chat)
        result = _build_diagnostics(tracker)
        assert result["circuit_open_count"] == 2
        cb_badges = [item for item in result["items"] if item.get("label") == "Circuit Breakers"]
        assert "2 open" in cb_badges[0]["value"]


class TestSuppressWindowDiagnostics:
    """Suppress window detection in diagnostics."""

    def test_no_suppress_when_old_replies(self):
        tracker = EchoTracker()
        # Inject an old reply timestamp (older than suppress window)
        old_ts = time.time() - _ECHO_SUPPRESS_WINDOW - 10
        tracker._chat_replies["chat-A"] = [old_ts]
        result = _build_diagnostics(tracker)
        assert result["suppress_active_count"] == 0

    def test_suppress_detected_with_recent_reply(self):
        tracker = EchoTracker()
        tracker.track_sent("t1", "hello", chat_guid="chat-A")
        result = _build_diagnostics(tracker)
        assert result["suppress_active_count"] == 1
        sw_badges = [item for item in result["items"] if item.get("label") == "Suppress Windows"]
        assert len(sw_badges) == 1
        assert sw_badges[0]["variant"] == "warning"

    def test_multiple_suppress_windows(self):
        tracker = EchoTracker()
        tracker.track_sent("t1", "hello", chat_guid="chat-A")
        tracker.track_sent("t2", "world", chat_guid="chat-B")
        result = _build_diagnostics(tracker)
        assert result["suppress_active_count"] == 2


class TestSummaryAggregation:
    """Summary badges aggregate correctly across chats."""

    def test_mixed_state_aggregation(self):
        tracker = EchoTracker()

        # chat-A: circuit breaker open (5 replies) + suppress active
        for i in range(_CIRCUIT_BREAKER_MAX):
            tracker.track_sent(f"tA{i}", f"msgA{i}", chat_guid="chat-A")

        # chat-B: just one reply (suppress active, no breaker)
        tracker.track_sent("tB0", "msgB0", chat_guid="chat-B")

        # chat-C: only sent content, no reply timestamps
        # (content-only tracking via _sent_content directly)
        from integrations.bluebubbles.echo_tracker import _text_hash
        tracker._sent_content["chat-C"] = {_text_hash("test"): time.time()}

        result = _build_diagnostics(tracker)
        assert result["tracked_chats"] == 3  # A + B + C
        assert result["circuit_open_count"] == 1  # only A
        assert result["suppress_active_count"] == 2  # A + B (recent replies)
