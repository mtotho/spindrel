"""Slack renderer: EPHEMERAL_MESSAGE → chat.postEphemeral.

Uses the same fake_http + reset fixtures as test_slack_renderer.py so
the renderer state is isolated between cases.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.domain.actor import ActorRef
from app.domain.capability import Capability
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.message import Message as DomainMessage
from app.domain.payloads import EphemeralMessagePayload
from integrations.slack import renderer as slack_renderer_mod
from integrations.slack.rate_limit import slack_rate_limiter
from integrations.slack.render_context import slack_render_contexts
from integrations.slack.renderer import SlackRenderer
from integrations.slack.target import SlackTarget

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_renderer_state():
    slack_render_contexts.reset()
    slack_rate_limiter.reset()
    slack_renderer_mod._register()
    yield
    slack_render_contexts.reset()
    slack_rate_limiter.reset()


@pytest.fixture(autouse=True)
def _mock_bot_attribution():
    with patch(
        "integrations.slack.renderer.bot_attribution",
        return_value={"username": "TB", "icon_emoji": ":robot:"},
    ) as m:
        yield m


@pytest.fixture
def fake_http():
    class FakeHTTP:
        def __init__(self):
            self.calls: list[dict] = []
            self._next = {"ok": True}

        def set_response(self, data: dict):
            self._next = data

        async def post(self, url, *, json=None, headers=None):
            self.calls.append({"url": url, "body": json})
            response = MagicMock()
            response.status_code = 200
            response.is_success = True
            response.headers = {}
            response.json = MagicMock(return_value=self._next)
            return response

    fake = FakeHTTP()
    with patch.object(slack_renderer_mod, "_http", fake):
        yield fake


def _ephemeral_event(
    *, recipient: str, text: str, thread_ts: str | None = None,
) -> tuple[ChannelEvent, SlackTarget]:
    msg = DomainMessage(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        role="assistant",
        content=text,
        created_at=datetime.now(timezone.utc),
        actor=ActorRef.bot("bot1"),
        metadata={"ephemeral": True, "recipient_user_id": recipient},
    )
    event = ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.EPHEMERAL_MESSAGE,
        payload=EphemeralMessagePayload(message=msg, recipient_user_id=recipient),
    )
    target = SlackTarget(
        channel_id="C01",
        token="xoxb-test",
        thread_ts=thread_ts,
        reply_in_thread=bool(thread_ts),
    )
    return event, target


class TestSlackEphemeralCapability:
    def test_renderer_declares_ephemeral(self):
        assert Capability.EPHEMERAL in SlackRenderer.capabilities


class TestEphemeralDelivery:
    async def test_posts_to_chat_post_ephemeral(self, fake_http):
        fake_http.set_response({"ok": True, "message_ts": "99.1"})
        event, target = _ephemeral_event(recipient="UALICE", text="secret")
        renderer = SlackRenderer()
        receipt = await renderer.render(event, target)
        assert receipt.success
        assert len(fake_http.calls) == 1
        call = fake_http.calls[0]
        assert call["url"].endswith("/chat.postEphemeral")
        body = call["body"]
        assert body["channel"] == "C01"
        assert body["user"] == "UALICE"
        assert body["text"] == "secret"
        # Bot attribution flows through the same path as NEW_MESSAGE.
        assert body.get("username") == "TB"

    async def test_respects_thread_ts_when_reply_in_thread(self, fake_http):
        fake_http.set_response({"ok": True})
        event, target = _ephemeral_event(
            recipient="UALICE", text="hi", thread_ts="1.23",
        )
        await SlackRenderer().render(event, target)
        body = fake_http.calls[0]["body"]
        assert body["thread_ts"] == "1.23"

    async def test_skipped_on_empty_text(self, fake_http):
        event, target = _ephemeral_event(recipient="UALICE", text="  ")
        receipt = await SlackRenderer().render(event, target)
        assert receipt.success
        assert receipt.skip_reason
        assert not fake_http.calls

    async def test_skipped_without_recipient(self, fake_http):
        event, target = _ephemeral_event(recipient="", text="hi")
        receipt = await SlackRenderer().render(event, target)
        assert receipt.success
        assert receipt.skip_reason
        assert not fake_http.calls
