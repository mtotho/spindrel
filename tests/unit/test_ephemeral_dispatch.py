"""Publisher-side ephemeral dispatch: capability-aware routing."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.domain.capability import Capability
from app.domain.channel_events import ChannelEventKind
from app.integrations import renderer_registry
from app.services import ephemeral_dispatch

pytestmark = pytest.mark.asyncio


CH_UUID = uuid.UUID("22222222-2222-2222-2222-222222222222")


class _FakeChannel:
    def __init__(self, client_id: str):
        self.id = CH_UUID
        self.client_id = client_id


class _FakeDB:
    """Minimal DB stand-in for the `_resolve_integration_id` path.

    Matches the subset of SQLAlchemy AsyncSession that the dispatch
    helper actually uses: ``async with async_session() as db:`` then
    ``await db.execute(...).scalar_one_or_none()``.
    """

    def __init__(self, channel: _FakeChannel | None):
        self._channel = channel

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **kw):
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=self._channel)
        return result


@pytest.fixture(autouse=True)
def _clean_registry():
    # Record what was there so tests that register fakes can cleanly restore.
    before = dict(renderer_registry._registry)
    yield
    renderer_registry._registry.clear()
    renderer_registry._registry.update(before)


class _FakeRenderer:
    def __init__(self, integration_id: str, caps: frozenset[Capability]):
        self.integration_id = integration_id
        self.capabilities = caps


def _install_channel(monkeypatch, channel: _FakeChannel | None):
    def fake_session():
        return _FakeDB(channel)
    monkeypatch.setattr(ephemeral_dispatch, "async_session", fake_session)


def _install_renderer(integration_id: str, caps: frozenset[Capability]):
    renderer_registry._registry[integration_id] = _FakeRenderer(integration_id, caps)


class TestDeliverEphemeralEphemeralPath:
    async def test_publishes_ephemeral_event_when_supported(self, monkeypatch):
        _install_channel(monkeypatch, _FakeChannel("slack:C01"))
        _install_renderer("slack", frozenset({Capability.TEXT, Capability.EPHEMERAL}))

        published: list[tuple] = []

        def fake_publish(channel_id, event):
            published.append((channel_id, event))
            return 1

        monkeypatch.setattr(ephemeral_dispatch, "publish_typed", fake_publish)

        result = await ephemeral_dispatch.deliver_ephemeral(
            channel_id=CH_UUID, bot_id="b1",
            recipient_user_id="UALICE", text="secret",
        )
        assert result == {"mode": "ephemeral", "integration_id": "slack"}
        assert len(published) == 1
        _, event = published[0]
        assert event.kind == ChannelEventKind.EPHEMERAL_MESSAGE
        assert event.payload.recipient_user_id == "UALICE"
        assert event.payload.message.content == "secret"


class TestDeliverEphemeralFallback:
    async def test_degraded_broadcast_when_capability_missing(self, monkeypatch):
        _install_channel(monkeypatch, _FakeChannel("bluebubbles:+15551234"))
        _install_renderer("bluebubbles", frozenset({Capability.TEXT}))

        broadcasts: list[dict] = []

        async def fake_enqueue(*, channel_id, bot_id, text):
            broadcasts.append({"channel_id": channel_id, "bot_id": bot_id, "text": text})

        monkeypatch.setattr(ephemeral_dispatch, "_enqueue_broadcast", fake_enqueue)

        result = await ephemeral_dispatch.deliver_ephemeral(
            channel_id=CH_UUID, bot_id="b1",
            recipient_user_id="UBOB", text="hi bob",
        )
        assert result["mode"] == "degraded_broadcast"
        assert len(broadcasts) == 1
        # The visibility marker should precede the actual text.
        assert "Private reply intended for" in broadcasts[0]["text"]
        assert broadcasts[0]["text"].endswith("hi bob")

    async def test_slack_variant_uses_native_mention_in_marker(self, monkeypatch):
        """If Slack lost its EPHEMERAL capability for some reason, the fallback
        still uses the Slack-native mention syntax so recipients see the intent."""
        _install_channel(monkeypatch, _FakeChannel("slack:C01"))
        _install_renderer("slack", frozenset({Capability.TEXT}))  # note: no EPHEMERAL

        broadcasts: list[dict] = []

        async def fake_enqueue(*, channel_id, bot_id, text):
            broadcasts.append({"text": text})

        monkeypatch.setattr(ephemeral_dispatch, "_enqueue_broadcast", fake_enqueue)

        result = await ephemeral_dispatch.deliver_ephemeral(
            channel_id=CH_UUID, bot_id="b1",
            recipient_user_id="UALICE", text="secret",
        )
        assert result["mode"] == "degraded_broadcast"
        assert broadcasts[0]["text"].startswith(":lock:")
        assert "<@UALICE>" in broadcasts[0]["text"]


class TestDeliverEphemeralErrors:
    async def test_empty_text_returns_error(self, monkeypatch):
        result = await ephemeral_dispatch.deliver_ephemeral(
            channel_id=CH_UUID, bot_id="b1", recipient_user_id="U", text="   ",
        )
        assert result["mode"] == "error"
        assert "empty" in result["error"].lower()

    async def test_missing_channel_returns_error(self, monkeypatch):
        _install_channel(monkeypatch, None)
        result = await ephemeral_dispatch.deliver_ephemeral(
            channel_id=CH_UUID, bot_id="b1", recipient_user_id="U", text="hi",
        )
        assert result["mode"] == "error"
        assert "not bound" in result["error"]
