"""Slack durable ``NEW_MESSAGE`` delivery tests."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.domain.actor import ActorRef
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.message import Message as DomainMessage
from app.domain.payloads import MessagePayload
from integrations.slack import transport as slack_transport_mod
from integrations.slack.message_delivery import SlackMessageDelivery
from integrations.slack.rate_limit import slack_rate_limiter
from integrations.slack.render_context import slack_render_contexts
from integrations.slack.renderer import SlackRenderer
from integrations.slack.target import SlackTarget

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_delivery_state():
    slack_render_contexts.reset()
    slack_rate_limiter.reset()
    yield
    slack_render_contexts.reset()
    slack_rate_limiter.reset()


@pytest.fixture
def fake_http():
    class FakeHTTP:
        def __init__(self):
            self.calls: list[dict] = []
            self._next_response: dict | None = None
            self._next_status: int = 200
            self._next_headers: dict[str, str] = {}

        def set_response(
            self,
            data: dict,
            *,
            status_code: int = 200,
            headers: dict[str, str] | None = None,
        ):
            self._next_response = data
            self._next_status = status_code
            self._next_headers = headers or {}

        async def post(self, url, *, json=None, headers=None):
            self.calls.append({"url": url, "body": json, "headers": headers})
            response = MagicMock()
            response.status_code = self._next_status
            response.headers = self._next_headers
            response.is_success = 200 <= self._next_status < 300
            response.json = MagicMock(return_value=self._next_response or {"ok": True})
            return response

    fake = FakeHTTP()
    with patch.object(slack_transport_mod, "_http", fake):
        yield fake


def _delivery() -> SlackMessageDelivery:
    return SlackMessageDelivery(
        call_slack=slack_transport_mod.call_slack,
        bot_attribution=lambda _bot_id: {
            "username": "Test Bot",
            "icon_emoji": ":robot:",
        },
        tool_result_rendering=SlackRenderer.tool_result_rendering,
    )


def _slack_target(
    channel_id: str = "C123",
    *,
    thread_ts: str | None = None,
    reply_in_thread: bool = False,
) -> SlackTarget:
    return SlackTarget(
        channel_id=channel_id,
        token="xoxb-test-token",
        thread_ts=thread_ts,
        reply_in_thread=reply_in_thread,
    )


def _calls_to(fake_http, method: str) -> list[dict]:
    return [
        call for call in fake_http.calls
        if call["url"] == f"https://slack.com/api/{method}"
    ]


def _new_message_event(
    role: str = "assistant",
    content: str = "hi",
    *,
    channel_id: uuid.UUID | None = None,
    msg_id: uuid.UUID | None = None,
    actor: ActorRef | None = None,
    metadata: dict | None = None,
    correlation_id: uuid.UUID | None = None,
) -> ChannelEvent:
    cid = channel_id if channel_id is not None else uuid.uuid4()
    if actor is None:
        if role == "user":
            actor = ActorRef.user("test-user", display_name="Alice")
        elif role == "tool":
            actor = ActorRef(kind="tool", id="test-tool", display_name=None, avatar=None)
        elif role == "system":
            actor = ActorRef.system("system")
        else:
            actor = ActorRef.bot("test-bot")
    return ChannelEvent(
        channel_id=cid,
        kind=ChannelEventKind.NEW_MESSAGE,
        payload=MessagePayload(
            message=DomainMessage(
                id=msg_id if msg_id is not None else uuid.uuid4(),
                session_id=uuid.uuid4(),
                role=role,
                content=content,
                created_at=datetime.now(timezone.utc),
                actor=actor,
                correlation_id=correlation_id,
                metadata=metadata or {},
                channel_id=cid,
            ),
        ),
    )


class TestSlackMessageDelivery:
    async def test_posts_assistant_message_with_attribution(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000002.0"})

        receipt = await _delivery().render(_new_message_event(), _slack_target("C123"))

        assert receipt.success is True
        assert len(_calls_to(fake_http, "chat.postMessage")) == 1
        assert [c["body"]["name"] for c in _calls_to(fake_http, "reactions.add")] == [
            "thumbsup",
            "thumbsdown",
        ]
        call = _calls_to(fake_http, "chat.postMessage")[0]
        assert call["url"] == "https://slack.com/api/chat.postMessage"
        assert call["body"]["channel"] == "C123"
        assert call["body"]["username"] == "Test Bot"

    async def test_skips_tool_role(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000002.1"})

        receipt = await _delivery().render(
            _new_message_event(role="tool", content='{"ok": true, "bytes": 1181}'),
            _slack_target("C123"),
        )

        assert receipt.success is True
        assert receipt.skip_reason is not None
        assert len(fake_http.calls) == 0

    async def test_skips_system_role(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000002.2"})

        receipt = await _delivery().render(
            _new_message_event(role="system", content="[datetime] ..."),
            _slack_target("C123"),
        )

        assert receipt.skip_reason is not None
        assert len(fake_http.calls) == 0

    async def test_assistant_during_active_turn_updates_placeholder(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000002.3"})
        turn_id = uuid.uuid4()
        ctx = slack_render_contexts.get_or_create(
            "C123", str(turn_id), bot_id="test-bot"
        )
        ctx.thinking_ts = "1700000000.123"
        ctx.thinking_channel = "C123"

        receipt = await _delivery().render(
            _new_message_event(
                role="assistant",
                content="Final answer from outbox",
                correlation_id=turn_id,
            ),
            _slack_target("C123"),
        )

        assert receipt.success is True
        assert receipt.skip_reason is None
        assert len(_calls_to(fake_http, "chat.update")) == 1
        assert [c["body"]["name"] for c in _calls_to(fake_http, "reactions.add")] == [
            "thumbsup",
            "thumbsdown",
        ]
        assert _calls_to(fake_http, "chat.update")[0]["url"] == "https://slack.com/api/chat.update"
        assert "Final answer" in _calls_to(fake_http, "chat.update")[0]["body"]["text"]
        assert slack_render_contexts.get("C123", str(turn_id)) is None

    async def test_assistant_no_turn_context_posts_new_message(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000002.4"})
        assert not slack_render_contexts.has_active_turn("C123")

        receipt = await _delivery().render(
            _new_message_event(role="assistant", content="durable delivery"),
            _slack_target("C123"),
        )

        assert receipt.success is True
        assert len(_calls_to(fake_http, "chat.postMessage")) == 1
        assert [c["body"]["name"] for c in _calls_to(fake_http, "reactions.add")] == [
            "thumbsup",
            "thumbsdown",
        ]
        assert _calls_to(fake_http, "chat.postMessage")[0]["url"] == "https://slack.com/api/chat.postMessage"

    async def test_post_failure_returns_delivery_receipt(self, fake_http):
        fake_http.set_response({}, status_code=500)

        receipt = await _delivery().render(
            _new_message_event(role="assistant", content="durable delivery"),
            _slack_target("C123"),
        )

        assert receipt.success is False
        assert receipt.retryable is True
        assert "HTTP 500" in (receipt.error or "")

    async def test_workflow_assistant_still_posts(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000002.4"})
        assert not slack_render_contexts.has_active_turn("C123")

        receipt = await _delivery().render(
            _new_message_event(role="assistant", content="workflow step 1 done"),
            _slack_target("C123"),
        )

        assert receipt.success is True
        assert len(_calls_to(fake_http, "chat.postMessage")) == 1
        assert len(_calls_to(fake_http, "reactions.add")) == 2

    async def test_skips_slack_origin_user_message_echo_via_metadata(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000002.6"})

        receipt = await _delivery().render(
            _new_message_event(
                role="user",
                content="Test from slack",
                actor=ActorRef.user("U06STGBF4Q0", display_name="Michael"),
                metadata={"source": "slack", "sender_id": "slack:U06STGBF4Q0"},
            ),
            _slack_target("C123"),
        )

        assert receipt.success is True
        assert receipt.skip_reason is not None
        assert "echo" in receipt.skip_reason
        assert len(fake_http.calls) == 0

    async def test_skips_slack_origin_user_message_echo_legacy_actor_prefix(
        self, fake_http
    ):
        fake_http.set_response({"ok": True, "ts": "1700000002.6"})

        receipt = await _delivery().render(
            _new_message_event(
                role="user",
                content="Test from slack",
                actor=ActorRef.user("slack:U06STGBF4Q0", display_name="Michael"),
            ),
            _slack_target("C123"),
        )

        assert receipt.success is True
        assert receipt.skip_reason is not None
        assert "echo" in receipt.skip_reason
        assert len(fake_http.calls) == 0

    async def test_still_mirrors_cross_integration_user_message(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000002.7"})

        receipt = await _delivery().render(
            _new_message_event(
                role="user",
                content="hi from web",
                actor=ActorRef.user(
                    "550e8400-e29b-41d4-a716-446655440000",
                    display_name="Alice",
                ),
            ),
            _slack_target("C123"),
        )

        assert receipt.success is True
        assert receipt.skip_reason is None
        assert len(fake_http.calls) == 1
        assert fake_http.calls[0]["body"]["username"] == "Alice"

    async def test_user_message_never_updates_thinking_placeholder(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000002.8"})
        turn_id = uuid.uuid4()
        ctx = slack_render_contexts.get_or_create(
            "C123", str(turn_id), bot_id="test-bot"
        )
        ctx.thinking_ts = "1700000000.777"
        ctx.thinking_channel = "C123"

        receipt = await _delivery().render(
            _new_message_event(
                role="user",
                content="hey rolland, can you get_weather?",
                actor=ActorRef.user(
                    "550e8400-e29b-41d4-a716-446655440000",
                    display_name="Michael",
                ),
                correlation_id=turn_id,
            ),
            _slack_target("C123"),
        )

        assert receipt.success is True
        assert len(fake_http.calls) == 1
        call = fake_http.calls[0]
        assert call["url"] == "https://slack.com/api/chat.postMessage"
        assert call["body"]["username"] == "Michael"
        assert slack_render_contexts.get("C123", str(turn_id)) is ctx
        assert ctx.thinking_ts == "1700000000.777"

    async def test_no_dedup_state_held_across_calls(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000002.5"})
        delivery = _delivery()
        target = _slack_target("C123")

        assert not hasattr(delivery, "_posted_set")
        assert not hasattr(delivery, "_posted_order")

        msg_id = uuid.uuid4()
        cid = uuid.uuid4()
        ev = _new_message_event(
            role="user", content="hi from web", channel_id=cid, msg_id=msg_id,
        )

        r1 = await delivery.render(ev, target)
        r2 = await delivery.render(ev, target)

        assert r1.success is True
        assert r1.skip_reason is None
        assert r2.success is True
        assert r2.skip_reason is None
        assert len(fake_http.calls) == 2
