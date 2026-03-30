"""Tests for Frigate MQTT event filtering, cooldown, and message formatting."""

import time
from unittest.mock import AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — build Frigate event payloads
# ---------------------------------------------------------------------------


def _make_event(
    *,
    event_type: str = "new",
    camera: str = "front_door",
    label: str = "person",
    score: float = 0.85,
    zones: list[str] | None = None,
    event_id: str = "evt-123",
    has_snapshot: bool = True,
    has_clip: bool = False,
    start_time: float | None = None,
) -> dict:
    """Build a Frigate MQTT event payload matching real Frigate schema."""
    after = {
        "id": event_id,
        "camera": camera,
        "label": label,
        "top_score": score,
        "current_zones": zones or [],
        "zones": zones or [],
        "has_snapshot": has_snapshot,
        "has_clip": has_clip,
        "start_time": start_time or time.time(),
    }
    return {
        "type": event_type,
        "before": {},
        "after": after,
    }


# ---------------------------------------------------------------------------
# Import helpers — patch env vars before importing module functions
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_module(monkeypatch):
    """Reset module-level state between tests."""
    # Set baseline env so the module loads cleanly
    monkeypatch.setenv("FRIGATE_MQTT_BROKER", "localhost")
    monkeypatch.setenv("FRIGATE_BOT_ID", "test-bot")
    monkeypatch.setenv("FRIGATE_MQTT_CAMERAS", "")
    monkeypatch.setenv("FRIGATE_MQTT_LABELS", "")
    monkeypatch.setenv("FRIGATE_MQTT_MIN_SCORE", "0.6")
    monkeypatch.setenv("FRIGATE_MQTT_COOLDOWN", "300")

    # Force reimport to pick up env changes
    import importlib
    import integrations.frigate.mqtt_listener as mod

    importlib.reload(mod)
    mod.reset_cooldowns()
    yield mod


# ---------------------------------------------------------------------------
# should_process_event tests
# ---------------------------------------------------------------------------


class TestShouldProcessEvent:
    def test_accepts_new_event_above_threshold(self, _clean_module):
        mod = _clean_module
        event = _make_event(score=0.9)
        assert mod.should_process_event(event) is True

    def test_rejects_update_event(self, _clean_module):
        mod = _clean_module
        event = _make_event(event_type="update")
        assert mod.should_process_event(event) is False

    def test_rejects_end_event(self, _clean_module):
        mod = _clean_module
        event = _make_event(event_type="end")
        assert mod.should_process_event(event) is False

    def test_rejects_low_score(self, _clean_module):
        mod = _clean_module
        event = _make_event(score=0.3)
        assert mod.should_process_event(event) is False

    def test_accepts_score_at_threshold(self, _clean_module):
        mod = _clean_module
        event = _make_event(score=0.6)
        assert mod.should_process_event(event) is True

    def test_camera_filter_allows_matching(self, _clean_module, monkeypatch):
        import importlib

        monkeypatch.setenv("FRIGATE_MQTT_CAMERAS", "front_door,back_yard")
        mod = _clean_module
        importlib.reload(mod)
        mod.reset_cooldowns()

        event = _make_event(camera="front_door")
        assert mod.should_process_event(event) is True

    def test_camera_filter_rejects_non_matching(self, _clean_module, monkeypatch):
        import importlib

        monkeypatch.setenv("FRIGATE_MQTT_CAMERAS", "front_door,back_yard")
        mod = _clean_module
        importlib.reload(mod)
        mod.reset_cooldowns()

        event = _make_event(camera="garage")
        assert mod.should_process_event(event) is False

    def test_label_filter_allows_matching(self, _clean_module, monkeypatch):
        import importlib

        monkeypatch.setenv("FRIGATE_MQTT_LABELS", "person,car")
        mod = _clean_module
        importlib.reload(mod)
        mod.reset_cooldowns()

        event = _make_event(label="person")
        assert mod.should_process_event(event) is True

    def test_label_filter_rejects_non_matching(self, _clean_module, monkeypatch):
        import importlib

        monkeypatch.setenv("FRIGATE_MQTT_LABELS", "person,car")
        mod = _clean_module
        importlib.reload(mod)
        mod.reset_cooldowns()

        event = _make_event(label="dog")
        assert mod.should_process_event(event) is False

    def test_empty_filters_accept_all(self, _clean_module):
        mod = _clean_module
        event = _make_event(camera="any_cam", label="any_label")
        assert mod.should_process_event(event) is True

    def test_missing_type_field_rejected(self, _clean_module):
        mod = _clean_module
        event = {"before": {}, "after": {"camera": "x", "label": "y", "top_score": 0.9}}
        assert mod.should_process_event(event) is False


# ---------------------------------------------------------------------------
# Cooldown tests
# ---------------------------------------------------------------------------


class TestCooldown:
    def test_first_event_allowed(self, _clean_module):
        mod = _clean_module
        assert mod.check_cooldown("cam1", "person", now=1000.0) is True

    def test_second_event_within_cooldown_blocked(self, _clean_module):
        mod = _clean_module
        mod.check_cooldown("cam1", "person", now=1000.0)
        assert mod.check_cooldown("cam1", "person", now=1100.0) is False

    def test_event_after_cooldown_allowed(self, _clean_module):
        mod = _clean_module
        mod.check_cooldown("cam1", "person", now=1000.0)
        assert mod.check_cooldown("cam1", "person", now=1301.0) is True

    def test_different_camera_independent(self, _clean_module):
        mod = _clean_module
        mod.check_cooldown("cam1", "person", now=1000.0)
        assert mod.check_cooldown("cam2", "person", now=1001.0) is True

    def test_different_label_independent(self, _clean_module):
        mod = _clean_module
        mod.check_cooldown("cam1", "person", now=1000.0)
        assert mod.check_cooldown("cam1", "car", now=1001.0) is True

    def test_zero_cooldown_always_allows(self, _clean_module, monkeypatch):
        import importlib

        monkeypatch.setenv("FRIGATE_MQTT_COOLDOWN", "0")
        mod = _clean_module
        importlib.reload(mod)
        mod.reset_cooldowns()

        mod.check_cooldown("cam1", "person", now=1000.0)
        assert mod.check_cooldown("cam1", "person", now=1000.1) is True

    def test_cooldown_integrated_with_should_process(self, _clean_module):
        """Second identical event within cooldown is filtered."""
        mod = _clean_module
        event = _make_event(camera="cam1", label="person", score=0.9)

        assert mod.should_process_event(event) is True
        assert mod.should_process_event(event) is False  # cooldown


# ---------------------------------------------------------------------------
# Message formatting tests
# ---------------------------------------------------------------------------


class TestFormatEventMessage:
    def test_basic_format(self, _clean_module):
        mod = _clean_module
        event = _make_event(
            camera="front_door",
            label="person",
            score=0.92,
            event_id="evt-abc",
            zones=["driveway"],
            has_snapshot=True,
            has_clip=True,
            start_time=1700000000.0,
        )
        msg = mod.format_event_message(event)

        assert "[Frigate event] New detection on front_door" in msg
        assert "person" in msg
        assert "92%" in msg
        assert "driveway" in msg
        assert "evt-abc" in msg
        assert "Snapshot available: True" in msg
        assert "Clip available: True" in msg
        assert "frigate_event_snapshot" in msg

    def test_no_zones(self, _clean_module):
        mod = _clean_module
        event = _make_event(zones=[])
        msg = mod.format_event_message(event)
        assert "Zones" not in msg

    def test_multiple_zones(self, _clean_module):
        mod = _clean_module
        event = _make_event(zones=["front_yard", "sidewalk"])
        msg = mod.format_event_message(event)
        assert "front_yard, sidewalk" in msg

    def test_score_formatting_low(self, _clean_module):
        mod = _clean_module
        event = _make_event(score=0.6)
        msg = mod.format_event_message(event)
        assert "60%" in msg


# ---------------------------------------------------------------------------
# post_chat tests
# ---------------------------------------------------------------------------


class TestPostChat:
    @pytest.mark.asyncio
    async def test_post_chat_sends_correct_payload(self, _clean_module):
        mod = _clean_module

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = lambda: None

        with patch.object(mod.http, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            await mod.post_chat("test message")

            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
            assert payload["message"] == "test message"
            assert payload["bot_id"] == "test-bot"
            assert payload["client_id"] == "frigate:events"

    @pytest.mark.asyncio
    async def test_post_chat_handles_error_gracefully(self, _clean_module):
        mod = _clean_module

        with patch.object(mod.http, "post", new_callable=AsyncMock, side_effect=Exception("connection refused")):
            # Should not raise
            await mod.post_chat("test message")
