"""Phase F — SlackRenderer unit tests.

These tests mock the shared httpx client used by Slack transport
(``integrations.slack.transport._http``) so we can assert exactly which
Slack API methods get called for each ChannelEventKind without doing
real HTTP. The rate limiter and render-context registry are reset
between tests so state doesn't leak.

The single most important test is the streaming-edit coalesce + safety
pass — that's the direct fix for the user-reported "Slack mobile
sometimes never refreshes" symptom that motivated this whole track.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.actor import ActorRef
from app.domain.capability import Capability
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.dispatch_target import NoneTarget
from integrations.slack.target import SlackTarget
from app.domain.message import Message as DomainMessage
from app.domain.payloads import (
    ApprovalRequestedPayload,
    AttachmentDeletedPayload,
    EphemeralMessagePayload,
    MessagePayload,
    TurnEndedPayload,
    TurnStartedPayload,
    TurnStreamTokenPayload,
    TurnStreamToolStartPayload,
)
from app.integrations import renderer_registry
from app.integrations.renderer import DeliveryReceipt
from integrations.slack import renderer as slack_renderer_mod
from integrations.slack import streaming as slack_streaming_mod
from integrations.slack import transport as slack_transport_mod
from integrations.slack.rate_limit import slack_rate_limiter
from integrations.slack.render_context import (
    STREAM_FLUSH_INTERVAL,
    slack_render_contexts,
)
from integrations.slack.renderer import SlackRenderer

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_renderer_state():
    """Reset render-context + rate-limiter state between tests so state
    from one test doesn't bleed into another. Also re-register the
    SlackRenderer in case a previous test cleared the registry.
    """
    slack_render_contexts.reset()
    slack_rate_limiter.reset()
    # Other test files (e.g. test_renderer_registry.py) call
    # ``renderer_registry.clear()`` and don't restore Slack — re-run
    # the self-register helper so SlackRenderer is always available
    # for these tests. Idempotent.
    slack_renderer_mod._register()
    yield
    slack_render_contexts.reset()
    slack_rate_limiter.reset()


@pytest.fixture
def fake_http():
    """Replace ``slack_transport_mod._http`` with an AsyncMock that returns
    a configurable Slack API response.

    Tests use ``fake_http.set_response(method, payload)`` to script the
    next call's response. The mock records every call so assertions can
    inspect URL + body + headers.
    """
    class FakeHTTP:
        def __init__(self):
            self.calls: list[dict] = []
            self._next_response: dict | None = None
            self._next_status: int = 200
            self._next_headers: dict[str, str] = {}
            self._raise: Exception | None = None

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
            self._raise = None

        def set_raise(self, exc: Exception):
            self._raise = exc

        async def post(self, url, *, json=None, headers=None):
            self.calls.append({"url": url, "body": json, "headers": headers})
            if self._raise is not None:
                raise self._raise
            response = MagicMock()
            response.status_code = self._next_status
            response.headers = self._next_headers
            response.is_success = 200 <= self._next_status < 300
            response.json = MagicMock(return_value=self._next_response or {"ok": True})
            return response

    fake = FakeHTTP()
    with patch.object(slack_transport_mod, "_http", fake):
        yield fake


@pytest.fixture(autouse=True)
def _mock_bot_attribution():
    """Stub bot_attribution so tests don't need a real bot config loaded."""
    with patch(
        "integrations.slack.renderer.bot_attribution",
        return_value={"username": "Test Bot", "icon_emoji": ":robot:"},
    ) as mock:
        yield mock


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


def _turn_started_event(turn_id: uuid.UUID, bot_id: str = "test-bot") -> ChannelEvent:
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.TURN_STARTED,
        payload=TurnStartedPayload(bot_id=bot_id, turn_id=turn_id, reason="user_message"),
    )


def _stream_token_event(
    turn_id: uuid.UUID, delta: str, bot_id: str = "test-bot"
) -> ChannelEvent:
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.TURN_STREAM_TOKEN,
        payload=TurnStreamTokenPayload(bot_id=bot_id, turn_id=turn_id, delta=delta),
    )


def _tool_start_event(turn_id: uuid.UUID, bot_id: str = "test-bot") -> ChannelEvent:
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.TURN_STREAM_TOOL_START,
        payload=TurnStreamToolStartPayload(
            bot_id=bot_id, turn_id=turn_id, tool_name="echo", arguments={},
        ),
    )


def _turn_ended_event(
    turn_id: uuid.UUID,
    bot_id: str = "test-bot",
    result: str | None = "Done!",
    error: str | None = None,
) -> ChannelEvent:
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.TURN_ENDED,
        payload=TurnEndedPayload(
            bot_id=bot_id,
            turn_id=turn_id,
            result=result,
            error=error,
            client_actions=[],
        ),
    )


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


def _approval_event(
    *,
    capability: dict | None = None,
) -> ChannelEvent:
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.APPROVAL_REQUESTED,
        payload=ApprovalRequestedPayload(
            approval_id="appr-1",
            bot_id="test-bot",
            tool_name="dangerous_tool",
            arguments={"x": 1},
            reason="Policy requires approval",
            capability=capability,
        ),
    )


def _ephemeral_event() -> ChannelEvent:
    msg = DomainMessage(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        role="assistant",
        content="secret",
        created_at=datetime.now(timezone.utc),
        actor=ActorRef.bot("test-bot"),
        metadata={"ephemeral": True, "recipient_user_id": "UALICE"},
    )
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.EPHEMERAL_MESSAGE,
        payload=EphemeralMessagePayload(message=msg, recipient_user_id="UALICE"),
    )


# ---------------------------------------------------------------------------
# Self-registration & capability declarations
# ---------------------------------------------------------------------------


class TestSlackRendererRegistration:
    def test_renderer_registered_under_slack(self):
        renderer = renderer_registry.get("slack")
        assert renderer is not None
        assert isinstance(renderer, SlackRenderer)

    def test_capability_set_includes_streaming_edit(self):
        # The whole point of Phase F's renderer is to drive
        # chat.update streaming edits cleanly. STREAMING_EDIT must
        # be declared.
        assert Capability.STREAMING_EDIT in SlackRenderer.capabilities
        assert Capability.TEXT in SlackRenderer.capabilities
        assert Capability.RICH_TEXT in SlackRenderer.capabilities
        assert Capability.APPROVAL_BUTTONS in SlackRenderer.capabilities


# ---------------------------------------------------------------------------
# Target validation
# ---------------------------------------------------------------------------


class TestTargetValidation:
    async def test_non_slack_target_fails_non_retryable(self, fake_http):
        renderer = SlackRenderer()
        receipt = await renderer.render(
            _turn_started_event(uuid.uuid4()),
            NoneTarget(),
        )
        assert receipt.success is False
        assert receipt.retryable is False
        assert "non-slack target" in (receipt.error or "")
        assert fake_http.calls == []  # short-circuit before any HTTP


# ---------------------------------------------------------------------------
# TURN_STARTED — placeholder posting
# ---------------------------------------------------------------------------


class TestTurnStarted:
    async def test_posts_thinking_placeholder(self, fake_http):
        fake_http.set_response({
            "ok": True,
            "ts": "1700000000.123",
            "channel": "C123",
        })
        renderer = SlackRenderer()
        turn_id = uuid.uuid4()
        target = _slack_target("C123")

        receipt = await renderer.render(_turn_started_event(turn_id), target)

        assert receipt.success is True
        assert receipt.external_id == "1700000000.123"
        assert len(fake_http.calls) == 1
        call = fake_http.calls[0]
        assert call["url"] == "https://slack.com/api/chat.postMessage"
        assert call["body"]["channel"] == "C123"
        assert "thinking" in call["body"]["text"].lower()
        assert call["headers"]["Authorization"] == "Bearer xoxb-test-token"

    async def test_idempotent_for_same_turn(self, fake_http):
        fake_http.set_response({
            "ok": True, "ts": "1700000000.123", "channel": "C123",
        })
        renderer = SlackRenderer()
        turn_id = uuid.uuid4()
        target = _slack_target("C123")

        await renderer.render(_turn_started_event(turn_id), target)
        await renderer.render(_turn_started_event(turn_id), target)

        # Second call short-circuits — only one chat.postMessage fired.
        assert len(fake_http.calls) == 1

    async def test_stuck_outbox_poll_does_not_block_placeholder(
        self, fake_http, monkeypatch
    ):
        async def stuck_count_pending_outbox(*_args, **_kwargs):
            await asyncio.sleep(10)

        monkeypatch.setattr(
            slack_streaming_mod,
            "count_pending_outbox",
            stuck_count_pending_outbox,
        )
        fake_http.set_response({
            "ok": True, "ts": "1700000000.123", "channel": "C123",
        })
        renderer = SlackRenderer()
        turn_id = uuid.uuid4()
        target = _slack_target("C123")

        receipt = await asyncio.wait_for(
            renderer.render(_turn_started_event(turn_id), target),
            timeout=0.5,
        )

        assert receipt.success is True
        assert len(fake_http.calls) == 1


# ---------------------------------------------------------------------------
# Streaming token coalesce + safety pass — THE bug fix
# ---------------------------------------------------------------------------


class TestStreamingCoalesce:
    async def test_first_token_after_window_calls_chat_update_once(self, fake_http):
        fake_http.set_response({
            "ok": True, "ts": "1700000000.123", "channel": "C123",
        })
        renderer = SlackRenderer()
        turn_id = uuid.uuid4()
        target = _slack_target("C123")

        # 1. Post the placeholder.
        await renderer.render(_turn_started_event(turn_id), target)
        assert len(fake_http.calls) == 1

        # 2. Force the debounce window to be elapsed by reaching back into
        #    the context registry. This is the unit-test cheat — in
        #    production the 0.8s wall clock fires the flush.
        ctx = slack_render_contexts.get("C123", str(turn_id))
        ctx.last_flush_at = time.monotonic() - (STREAM_FLUSH_INTERVAL + 0.1)

        # 3. First token: should fire one chat.update.
        await renderer.render(_stream_token_event(turn_id, "hello"), target)

        assert len(fake_http.calls) == 2
        update_call = fake_http.calls[1]
        assert update_call["url"] == "https://slack.com/api/chat.update"
        assert update_call["body"]["ts"] == "1700000000.123"
        assert "hello" in update_call["body"]["text"]

    async def test_tokens_inside_debounce_window_do_not_call_update(
        self, fake_http
    ):
        fake_http.set_response({
            "ok": True, "ts": "1700000000.123", "channel": "C123",
        })
        renderer = SlackRenderer()
        turn_id = uuid.uuid4()
        target = _slack_target("C123")

        await renderer.render(_turn_started_event(turn_id), target)
        # Mark the placeholder as just-flushed so the next tokens skip
        # the chat.update.
        ctx = slack_render_contexts.get("C123", str(turn_id))
        ctx.last_flush_at = time.monotonic()

        for delta in ("a", "b", "c", "d", "e"):
            await renderer.render(_stream_token_event(turn_id, delta), target)

        # Only the placeholder post fired — no chat.update calls.
        assert len(fake_http.calls) == 1
        # Accumulated text was buffered.
        assert ctx.accumulated_text == "abcde"

    async def test_force_flush_on_tool_start_clears_buffer(self, fake_http):
        fake_http.set_response({
            "ok": True, "ts": "1700000000.123", "channel": "C123",
        })
        renderer = SlackRenderer()
        turn_id = uuid.uuid4()
        target = _slack_target("C123")

        await renderer.render(_turn_started_event(turn_id), target)
        ctx = slack_render_contexts.get("C123", str(turn_id))
        # Buffer some text but don't trigger the debounce.
        ctx.last_flush_at = time.monotonic()
        await renderer.render(_stream_token_event(turn_id, "partial"), target)
        assert len(fake_http.calls) == 1  # placeholder only

        # Tool start should force-flush regardless of debounce.
        await renderer.render(_tool_start_event(turn_id), target)
        assert len(fake_http.calls) == 2
        flush_call = fake_http.calls[1]
        assert flush_call["url"] == "https://slack.com/api/chat.update"
        assert "partial" in flush_call["body"]["text"]


# ---------------------------------------------------------------------------
# TURN_ENDED — final placeholder update
# ---------------------------------------------------------------------------


class TestTurnEnded:
    async def test_updates_placeholder_with_final_text(self, fake_http):
        fake_http.set_response({
            "ok": True, "ts": "1700000000.123", "channel": "C123",
        })
        renderer = SlackRenderer()
        turn_id = uuid.uuid4()
        target = _slack_target("C123")

        await renderer.render(_turn_started_event(turn_id), target)
        await renderer.render(
            _turn_ended_event(turn_id, result="Final answer"), target,
        )

        # Placeholder POST + final chat.update.
        assert len(fake_http.calls) == 2
        final_call = fake_http.calls[1]
        assert final_call["url"] == "https://slack.com/api/chat.update"
        assert "Final answer" in final_call["body"]["text"]

    async def test_renders_error_when_result_empty(self, fake_http):
        fake_http.set_response({
            "ok": True, "ts": "1700000000.123", "channel": "C123",
        })
        renderer = SlackRenderer()
        turn_id = uuid.uuid4()
        target = _slack_target("C123")

        await renderer.render(_turn_started_event(turn_id), target)
        await renderer.render(
            _turn_ended_event(turn_id, result=None, error="cancelled"),
            target,
        )

        final_call = fake_http.calls[1]
        assert "Agent error" in final_call["body"]["text"]
        assert "cancelled" in final_call["body"]["text"]

    async def test_no_placeholder_is_noop(self, fake_http):
        # If TURN_ENDED arrives without a prior TURN_STARTED, there's
        # no placeholder to update. The outbox NEW_MESSAGE handles
        # delivery — TURN_ENDED is just the streaming UX path.
        fake_http.set_response({"ok": True, "ts": "1700000001.456"})
        renderer = SlackRenderer()
        turn_id = uuid.uuid4()
        target = _slack_target("C123")

        receipt = await renderer.render(
            _turn_ended_event(turn_id, result="standalone"), target,
        )

        assert receipt.success is True
        assert len(fake_http.calls) == 0  # no HTTP calls — outbox handles it

    async def test_preserves_render_context_for_new_message(self, fake_http):
        # TURN_ENDED no longer discards context — NEW_MESSAGE owns cleanup.
        fake_http.set_response({
            "ok": True, "ts": "1700000000.123", "channel": "C123",
        })
        renderer = SlackRenderer()
        turn_id = uuid.uuid4()
        target = _slack_target("C123")

        await renderer.render(_turn_started_event(turn_id), target)
        assert slack_render_contexts.get("C123", str(turn_id)) is not None

        await renderer.render(_turn_ended_event(turn_id), target)
        # Context preserved for NEW_MESSAGE to pick up the thinking_ts.
        assert slack_render_contexts.get("C123", str(turn_id)) is not None

    async def test_does_not_post_overflow_chunks(self, fake_http):
        # TURN_ENDED only updates the placeholder — no chat.postMessage
        # for overflow chunks. That's NEW_MESSAGE's job.
        fake_http.set_response({
            "ok": True, "ts": "1700000000.123", "channel": "C123",
        })
        renderer = SlackRenderer()
        turn_id = uuid.uuid4()
        target = _slack_target("C123")

        await renderer.render(_turn_started_event(turn_id), target)
        # A very long result that would split into multiple chunks.
        long_result = "A" * 5000
        await renderer.render(
            _turn_ended_event(turn_id, result=long_result), target,
        )

        # Only placeholder POST + one chat.update — no overflow postMessages.
        post_calls = [
            c for c in fake_http.calls
            if "chat.postMessage" in c["url"]
        ]
        update_calls = [
            c for c in fake_http.calls
            if "chat.update" in c["url"]
        ]
        assert len(post_calls) == 1  # just the placeholder
        assert len(update_calls) == 1  # just the final update

    async def test_turn_ended_serializes_against_inflight_flush(self, fake_http):
        """Regression for the Phase F race.

        ``SlackRenderer`` is invoked via two paths concurrently — the
        ``subscribe_all`` bus subscription AND the outbox drainer.
        Without flush_lock serialization, ``_handle_turn_ended`` can
        fire its final ``chat.update`` while a streaming-token
        ``_do_flush`` PATCH is still in flight against the same ``ts``,
        and the two updates race. Slack's ``chat.update`` is idempotent
        on ``ts`` but NOT on body; the resulting final state is
        non-deterministic.

        We force the race deterministically by holding the renderer's
        ``flush_lock`` from outside before issuing TURN_ENDED, then
        releasing it. The fix makes ``_handle_turn_ended`` wait for the
        lock before touching ``ts`` — without the fix, this test races
        and TURN_ENDED's chat.update lands BEFORE the lock is released
        (i.e. before any in-flight streaming flush would have completed).
        """
        fake_http.set_response({
            "ok": True, "ts": "1700000000.123", "channel": "C123",
        })
        renderer = SlackRenderer()
        turn_id = uuid.uuid4()
        target = _slack_target("C123")

        # Set up the placeholder so the render context exists.
        await renderer.render(_turn_started_event(turn_id), target)
        ctx = slack_render_contexts.get("C123", str(turn_id))
        assert ctx is not None

        # Hold the flush lock from a fake "in-flight flush" task.
        await ctx.flush_lock.acquire()

        # Schedule TURN_ENDED — it should block on the lock.
        ended_task = asyncio.create_task(
            renderer.render(
                _turn_ended_event(turn_id, result="Final answer"), target,
            )
        )
        await asyncio.sleep(0.01)  # let it run to the lock acquire
        assert not ended_task.done(), (
            "TURN_ENDED should be waiting on flush_lock, not racing"
        )

        # Release the lock — now TURN_ENDED can proceed.
        ctx.flush_lock.release()
        receipt = await asyncio.wait_for(ended_task, timeout=1.0)

        assert receipt.success is True
        # The final chat.update fired exactly once with the result text.
        update_calls = [
            c for c in fake_http.calls
            if c["url"] == "https://slack.com/api/chat.update"
        ]
        assert len(update_calls) == 1
        assert "Final answer" in update_calls[0]["body"]["text"]


# ---------------------------------------------------------------------------
# NEW_MESSAGE routing
# ---------------------------------------------------------------------------


class TestNewMessageRouting:
    async def test_routes_new_message_to_message_delivery(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000002.0"})
        renderer = SlackRenderer()

        receipt = await renderer.render(_new_message_event(), _slack_target("C123"))

        assert receipt.success is True
        assert len(fake_http.calls) == 1
        call = fake_http.calls[0]
        assert call["url"] == "https://slack.com/api/chat.postMessage"
        assert call["body"]["channel"] == "C123"
        assert call["body"]["username"] == "Test Bot"


# ---------------------------------------------------------------------------
# APPROVAL_REQUESTED routing
# ---------------------------------------------------------------------------


class TestApprovalRequestedRouting:
    async def test_routes_approval_to_delivery(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000003.0"})
        with patch(
            "integrations.slack.approval_blocks.build_suggestions",
            return_value=[],
        ):
            receipt = await SlackRenderer().render(
                _approval_event(), _slack_target("C123"),
            )

        assert receipt.success is True
        assert len(fake_http.calls) == 1
        assert fake_http.calls[0]["url"] == "https://slack.com/api/chat.postMessage"
        assert "blocks" in fake_http.calls[0]["body"]


# ---------------------------------------------------------------------------
# EPHEMERAL_MESSAGE routing
# ---------------------------------------------------------------------------


class TestEphemeralMessageRouting:
    async def test_routes_ephemeral_to_delivery(self, fake_http):
        fake_http.set_response({"ok": True, "message_ts": "99.1"})

        receipt = await SlackRenderer().render(_ephemeral_event(), _slack_target("C123"))

        assert receipt.success is True
        assert len(fake_http.calls) == 1
        assert fake_http.calls[0]["url"] == "https://slack.com/api/chat.postEphemeral"
        assert fake_http.calls[0]["body"]["user"] == "UALICE"


# ---------------------------------------------------------------------------
# Slack 429 + non-2xx handling
# ---------------------------------------------------------------------------


class TestSlackErrorHandling:
    async def test_429_returns_retryable_failure_and_records_rate_limit(
        self, fake_http
    ):
        fake_http.set_response(
            {"ok": False, "error": "rate_limited"},
            status_code=429,
            headers={"Retry-After": "2"},
        )
        renderer = SlackRenderer()
        receipt = await renderer.render(
            _turn_started_event(uuid.uuid4()), _slack_target("C123"),
        )

        assert receipt.success is False
        assert receipt.retryable is True
        assert "429" in (receipt.error or "")

    async def test_invalid_auth_is_non_retryable(self, fake_http):
        fake_http.set_response({"ok": False, "error": "invalid_auth"})
        renderer = SlackRenderer()
        receipt = await renderer.render(
            _turn_started_event(uuid.uuid4()), _slack_target("C123"),
        )

        assert receipt.success is False
        assert receipt.retryable is False
        assert "invalid_auth" in (receipt.error or "")

    async def test_5xx_is_retryable(self, fake_http):
        fake_http.set_response({}, status_code=500)
        renderer = SlackRenderer()
        receipt = await renderer.render(
            _turn_started_event(uuid.uuid4()), _slack_target("C123"),
        )

        assert receipt.success is False
        assert receipt.retryable is True
