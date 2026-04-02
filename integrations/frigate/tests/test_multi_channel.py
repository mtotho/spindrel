"""Tests for multi-channel Frigate webhook fan-out and per-binding filtering."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.frigate.router import (
    ParsedEvent,
    frigate_webhook,
    matches_binding_filter,
    parse_event,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_EVENT = {
    "type": "new",
    "before": {},
    "after": {
        "id": "1234",
        "camera": "front_door",
        "label": "person",
        "top_score": 0.85,
        "current_zones": ["yard"],
        "has_snapshot": True,
        "has_clip": False,
        "start_time": 1711800000.0,
    },
}


def _make_request(payload: dict | None = None):
    """Build a mock FastAPI Request."""
    req = AsyncMock()
    req.json.return_value = payload or SAMPLE_EVENT
    return req


def _make_channel(channel_id=None, bot_id="default"):
    ch = MagicMock()
    ch.id = channel_id or uuid.uuid4()
    ch.bot_id = bot_id
    ch.client_id = None
    ch.integration = "frigate"
    ch.active_session_id = None
    return ch


def _make_binding(channel_id, client_id="frigate:events", dispatch_config=None):
    b = MagicMock()
    b.channel_id = channel_id
    b.client_id = client_id
    b.dispatch_config = dispatch_config
    return b


# ---------------------------------------------------------------------------
# parse_event tests
# ---------------------------------------------------------------------------


class TestParseEvent:
    def test_parses_new_event(self):
        result = parse_event(SAMPLE_EVENT)
        assert result is not None
        assert result.camera == "front_door"
        assert result.label == "person"
        assert result.score == 0.85

    def test_ignores_update_event(self):
        event = {**SAMPLE_EVENT, "type": "update"}
        assert parse_event(event) is None

    def test_ignores_end_event(self):
        event = {**SAMPLE_EVENT, "type": "end"}
        assert parse_event(event) is None

    def test_ignores_empty_data(self):
        event = {"type": "new", "before": {}, "after": {}}
        assert parse_event(event) is None


# ---------------------------------------------------------------------------
# matches_binding_filter tests
# ---------------------------------------------------------------------------


class TestMatchesBindingFilter:
    def test_no_filter_matches_all(self):
        event = ParsedEvent(camera="front_door", label="person", score=0.85, message="test")
        assert matches_binding_filter(event, None) is True
        assert matches_binding_filter(event, {}) is True

    def test_camera_filter_string(self):
        event = ParsedEvent(camera="front_door", label="person", score=0.85, message="test")
        assert matches_binding_filter(event, {"cameras": "front_door,driveway"}) is True
        assert matches_binding_filter(event, {"cameras": "backyard"}) is False

    def test_camera_filter_list(self):
        event = ParsedEvent(camera="front_door", label="person", score=0.85, message="test")
        assert matches_binding_filter(event, {"cameras": ["front_door", "driveway"]}) is True
        assert matches_binding_filter(event, {"cameras": ["backyard"]}) is False

    def test_label_filter_string(self):
        event = ParsedEvent(camera="front_door", label="person", score=0.85, message="test")
        assert matches_binding_filter(event, {"labels": "person,car"}) is True
        assert matches_binding_filter(event, {"labels": "dog"}) is False

    def test_label_filter_list(self):
        event = ParsedEvent(camera="front_door", label="person", score=0.85, message="test")
        assert matches_binding_filter(event, {"labels": ["person"]}) is True
        assert matches_binding_filter(event, {"labels": ["dog"]}) is False

    def test_min_score_filter(self):
        event = ParsedEvent(camera="front_door", label="person", score=0.85, message="test")
        assert matches_binding_filter(event, {"min_score": 0.7}) is True
        assert matches_binding_filter(event, {"min_score": 0.9}) is False

    def test_combined_filters(self):
        event = ParsedEvent(camera="front_door", label="person", score=0.85, message="test")
        config = {"cameras": "front_door", "labels": "person", "min_score": 0.8}
        assert matches_binding_filter(event, config) is True

        config_fail = {"cameras": "front_door", "labels": "car", "min_score": 0.8}
        assert matches_binding_filter(event, config_fail) is False


# ---------------------------------------------------------------------------
# Webhook fan-out tests
# ---------------------------------------------------------------------------


class TestWebhookFanOut:
    @pytest.mark.asyncio
    async def test_fanout_to_two_channels(self):
        """Same event dispatches to 2 channels with no filters."""
        ch1 = _make_channel()
        ch2 = _make_channel()
        b1 = _make_binding(ch1.id)
        b2 = _make_binding(ch2.id)
        pairs = [(ch1, b1), (ch2, b2)]

        session_ids = iter([uuid.uuid4(), uuid.uuid4()])

        async def mock_ensure(db, channel):
            return next(session_ids)

        request = _make_request()
        db = AsyncMock()

        with patch("integrations.frigate.router.parse_event") as mock_parse, \
             patch("integrations.frigate.router.resolve_all_channels_by_client_id", return_value=pairs), \
             patch("integrations.frigate.router.ensure_active_session", side_effect=mock_ensure) as mock_ensure_session, \
             patch("integrations.frigate.router.utils") as mock_utils:

            mock_parse.return_value = ParsedEvent(
                camera="front_door", label="person", score=0.85, message="test event",
            )
            mock_utils.inject_message = AsyncMock(return_value={
                "message_id": "m1", "session_id": "s1", "task_id": "t1",
            })

            result = await frigate_webhook(request, db)

        assert result["status"] == "processed"
        assert result["channels"] == 2
        assert len(result["results"]) == 2
        assert mock_ensure_session.call_count == 2
        assert mock_utils.inject_message.call_count == 2

    @pytest.mark.asyncio
    async def test_per_binding_camera_filter(self):
        """Channel with camera filter only receives matching events."""
        ch1 = _make_channel()
        ch2 = _make_channel()
        # ch1 only wants driveway
        b1 = _make_binding(ch1.id, dispatch_config={"cameras": "driveway"})
        # ch2 wants everything
        b2 = _make_binding(ch2.id)
        pairs = [(ch1, b1), (ch2, b2)]

        request = _make_request()
        db = AsyncMock()

        with patch("integrations.frigate.router.parse_event") as mock_parse, \
             patch("integrations.frigate.router.resolve_all_channels_by_client_id", return_value=pairs), \
             patch("integrations.frigate.router.ensure_active_session", return_value=uuid.uuid4()) as mock_ensure, \
             patch("integrations.frigate.router.utils") as mock_utils:

            mock_parse.return_value = ParsedEvent(
                camera="front_door", label="person", score=0.85, message="test",
            )
            mock_utils.inject_message = AsyncMock(return_value={
                "message_id": "m1", "session_id": "s1", "task_id": "t1",
            })

            result = await frigate_webhook(request, db)

        assert result["status"] == "processed"
        assert result["channels"] == 1
        # Only ch2 should have received the event
        assert mock_ensure.call_count == 1
        assert mock_utils.inject_message.call_count == 1

    @pytest.mark.asyncio
    async def test_per_binding_label_filter(self):
        """Channel with label filter skips non-matching labels."""
        ch1 = _make_channel()
        b1 = _make_binding(ch1.id, dispatch_config={"labels": "car"})
        pairs = [(ch1, b1)]

        request = _make_request()
        db = AsyncMock()

        with patch("integrations.frigate.router.parse_event") as mock_parse, \
             patch("integrations.frigate.router.resolve_all_channels_by_client_id", return_value=pairs), \
             patch("integrations.frigate.router.ensure_active_session") as mock_ensure, \
             patch("integrations.frigate.router.utils") as mock_utils:

            mock_parse.return_value = ParsedEvent(
                camera="front_door", label="person", score=0.85, message="test",
            )

            result = await frigate_webhook(request, db)

        assert result["status"] == "filtered"
        mock_ensure.assert_not_called()

    @pytest.mark.asyncio
    async def test_per_binding_min_score_filter(self):
        """Channel with min_score filter skips low-score events."""
        ch1 = _make_channel()
        b1 = _make_binding(ch1.id, dispatch_config={"min_score": 0.9})
        pairs = [(ch1, b1)]

        request = _make_request()
        db = AsyncMock()

        with patch("integrations.frigate.router.parse_event") as mock_parse, \
             patch("integrations.frigate.router.resolve_all_channels_by_client_id", return_value=pairs), \
             patch("integrations.frigate.router.ensure_active_session") as mock_ensure, \
             patch("integrations.frigate.router.utils"):

            mock_parse.return_value = ParsedEvent(
                camera="front_door", label="person", score=0.85, message="test",
            )

            result = await frigate_webhook(request, db)

        assert result["status"] == "filtered"
        mock_ensure.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_channels_filtered_returns_filtered_status(self):
        """When all channels' filters exclude the event, return 'filtered'."""
        ch1 = _make_channel()
        b1 = _make_binding(ch1.id, dispatch_config={"cameras": "backyard"})
        pairs = [(ch1, b1)]

        request = _make_request()
        db = AsyncMock()

        with patch("integrations.frigate.router.parse_event") as mock_parse, \
             patch("integrations.frigate.router.resolve_all_channels_by_client_id", return_value=pairs), \
             patch("integrations.frigate.router.ensure_active_session") as mock_ensure, \
             patch("integrations.frigate.router.utils"):

            mock_parse.return_value = ParsedEvent(
                camera="front_door", label="person", score=0.85, message="test",
            )

            result = await frigate_webhook(request, db)

        assert result["status"] == "filtered"
        assert result["channels"] == 1
        mock_ensure.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_bindings_falls_back_to_legacy(self):
        """When no channel bindings exist, falls back to legacy single-session."""
        request = _make_request()
        db = AsyncMock()
        session_id = uuid.uuid4()

        with patch("integrations.frigate.router.parse_event") as mock_parse, \
             patch("integrations.frigate.router.resolve_all_channels_by_client_id", return_value=[]), \
             patch("integrations.frigate.router.utils") as mock_utils:

            mock_parse.return_value = ParsedEvent(
                camera="front_door", label="person", score=0.85, message="test",
            )
            mock_utils.get_or_create_session = AsyncMock(return_value=session_id)
            mock_utils.inject_message = AsyncMock(return_value={
                "message_id": "m1", "session_id": str(session_id), "task_id": "t1",
            })

            result = await frigate_webhook(request, db)

        assert result["status"] == "processed"
        assert result["session_id"] == str(session_id)
        mock_utils.get_or_create_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_ignored_event_returns_ignored(self):
        """Non-new events are ignored."""
        request = _make_request({"type": "update", "before": {}, "after": {}})
        db = AsyncMock()

        with patch("integrations.frigate.router.parse_event", return_value=None):
            result = await frigate_webhook(request, db)

        assert result["status"] == "ignored"
