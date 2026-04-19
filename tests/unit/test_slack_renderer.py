"""Phase F — SlackRenderer unit tests.

These tests mock the shared httpx client used by the renderer
(``integrations.slack.renderer._http``) so we can assert exactly which
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
    MessagePayload,
    TurnEndedPayload,
    TurnStartedPayload,
    TurnStreamTokenPayload,
    TurnStreamToolStartPayload,
)
from app.integrations import renderer_registry
from app.integrations.renderer import DeliveryReceipt
from integrations.slack import renderer as slack_renderer_mod
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
    """Replace ``slack_renderer_mod._http`` with an AsyncMock that returns
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
    with patch.object(slack_renderer_mod, "_http", fake):
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
# NEW_MESSAGE — passive / mirror posts
# ---------------------------------------------------------------------------


class TestNewMessage:
    async def test_posts_assistant_message_with_attribution(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000002.0"})
        renderer = SlackRenderer()
        target = _slack_target("C123")

        receipt = await renderer.render(_new_message_event(), target)

        assert receipt.success is True
        assert len(fake_http.calls) == 1
        call = fake_http.calls[0]
        assert call["url"] == "https://slack.com/api/chat.postMessage"
        assert call["body"]["channel"] == "C123"
        assert call["body"]["username"] == "Test Bot"

    async def test_skips_tool_role(self, fake_http):
        """Regression: file_ops.write returns `{"ok": true, "bytes": N}` as
        a tool-role message. Without the role filter that raw JSON was
        being posted to Slack as a user-visible chat message under the
        bare Slack App name (no bot_attribution override)."""
        fake_http.set_response({"ok": True, "ts": "1700000002.1"})
        renderer = SlackRenderer()
        target = _slack_target("C123")

        receipt = await renderer.render(
            _new_message_event(role="tool", content='{"ok": true, "bytes": 1181}'),
            target,
        )

        assert receipt.success is True
        assert receipt.skip_reason is not None
        assert len(fake_http.calls) == 0

    async def test_skips_system_role(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000002.2"})
        renderer = SlackRenderer()
        target = _slack_target("C123")

        receipt = await renderer.render(
            _new_message_event(role="system", content="[datetime] …"),
            target,
        )

        assert receipt.skip_reason is not None
        assert len(fake_http.calls) == 0

    async def test_assistant_during_active_turn_updates_placeholder(self, fake_http):
        """When an assistant NEW_MESSAGE arrives during an active turn,
        the outbox updates the thinking placeholder instead of posting a
        duplicate. TURN_ENDED handles the streaming UX; NEW_MESSAGE is
        the sole durable delivery path."""
        fake_http.set_response({"ok": True, "ts": "1700000002.3"})
        renderer = SlackRenderer()
        target = _slack_target("C123")

        # Simulate an active turn with a thinking placeholder.
        turn_id = uuid.uuid4()
        ctx = slack_render_contexts.get_or_create(
            "C123", str(turn_id), bot_id="test-bot"
        )
        ctx.thinking_ts = "1700000000.123"
        ctx.thinking_channel = "C123"

        ev = _new_message_event(
            role="assistant",
            content="Final answer from outbox",
            correlation_id=turn_id,
        )

        receipt = await renderer.render(ev, target)

        assert receipt.success is True
        assert receipt.skip_reason is None
        # Should use chat.update (not chat.postMessage) for the placeholder.
        assert len(fake_http.calls) == 1
        assert fake_http.calls[0]["url"] == "https://slack.com/api/chat.update"
        assert "Final answer" in fake_http.calls[0]["body"]["text"]
        # Context should be cleaned up by NEW_MESSAGE.
        assert slack_render_contexts.get("C123", str(turn_id)) is None

    async def test_assistant_no_turn_context_posts_new_message(self, fake_http):
        """When no turn context exists (TURN_ENDED failed and discarded
        it, or process restarted), NEW_MESSAGE posts as a new message
        via the outbox — the durable fallback."""
        fake_http.set_response({"ok": True, "ts": "1700000002.4"})
        renderer = SlackRenderer()
        target = _slack_target("C123")

        assert not slack_render_contexts.has_active_turn("C123")

        receipt = await renderer.render(
            _new_message_event(role="assistant", content="durable delivery"),
            target,
        )

        assert receipt.success is True
        assert len(fake_http.calls) == 1
        assert fake_http.calls[0]["url"] == "https://slack.com/api/chat.postMessage"

    async def test_workflow_assistant_still_posts(self, fake_http):
        """Assistant messages published outside any active turn context
        (e.g. from ``workflow_executor.py``) are sideband messages with
        no TURN_ENDED to deliver them — NEW_MESSAGE must still reach
        Slack for the workflow UI to render."""
        fake_http.set_response({"ok": True, "ts": "1700000002.4"})
        renderer = SlackRenderer()
        target = _slack_target("C123")

        # No render context — no active turn.
        assert not slack_render_contexts.has_active_turn("C123")

        receipt = await renderer.render(
            _new_message_event(role="assistant", content="workflow step 1 done"),
            target,
        )

        assert receipt.success is True
        assert len(fake_http.calls) == 1

    async def test_skips_slack_origin_user_message_echo_via_metadata(self, fake_http):
        """Regression: user types in Slack, server pre-persists the user
        message and publishes NEW_MESSAGE, IntegrationDispatcherTask
        routes the event back to this renderer, which must NOT re-post
        the user's own message into their own Slack channel as an APP
        reply.

        Primary signal: ``metadata["source"] == "slack"`` set by
        ``integrations/slack/message_handlers.py:msg_metadata`` and
        threaded onto the DomainMessage by ``turn_worker._persist_and_
        publish_user_message``. The actor.id prefix is the legacy
        fallback exercised by the next test."""
        fake_http.set_response({"ok": True, "ts": "1700000002.6"})
        renderer = SlackRenderer()
        target = _slack_target("C123")

        # Note: actor.id intentionally has NO ``slack:`` prefix here
        # — we want to prove the metadata-based check is enough on
        # its own, so a future refactor that strips integration prefixes
        # from actor.id can't silently break echo prevention.
        ev = _new_message_event(
            role="user",
            # Per the ingest contract, content is the raw user text; Slack
            # identity lives in metadata. The echo-prevention check must
            # hinge on metadata.source (and the actor.id fallback below) —
            # NOT on any in-content prefix.
            content="Test from slack",
            actor=ActorRef.user("U06STGBF4Q0", display_name="Michael"),
            metadata={"source": "slack", "sender_id": "slack:U06STGBF4Q0"},
        )

        receipt = await renderer.render(ev, target)

        assert receipt.success is True
        assert receipt.skip_reason is not None
        assert "echo" in receipt.skip_reason
        assert len(fake_http.calls) == 0

    async def test_skips_slack_origin_user_message_echo_legacy_actor_prefix(
        self, fake_http
    ):
        """Legacy fallback: a Slack-origin user message that lacks
        ``metadata["source"]`` (e.g. persisted before the metadata fix
        landed) is still caught by the ``slack:`` prefix on actor.id."""
        fake_http.set_response({"ok": True, "ts": "1700000002.6"})
        renderer = SlackRenderer()
        target = _slack_target("C123")

        slack_origin_actor = ActorRef.user("slack:U06STGBF4Q0", display_name="Michael")
        ev = _new_message_event(
            role="user",
            content="Test from slack",
            actor=slack_origin_actor,
            # metadata empty — exercises the fallback path
        )

        receipt = await renderer.render(ev, target)

        assert receipt.success is True
        assert receipt.skip_reason is not None
        assert "echo" in receipt.skip_reason
        assert len(fake_http.calls) == 0

    async def test_still_mirrors_cross_integration_user_message(self, fake_http):
        """Cross-integration mirror: user types in the web UI in a
        channel that's also bound to Slack. The user message must still
        reach Slack — the echo filter only catches Slack-origin ids."""
        fake_http.set_response({"ok": True, "ts": "1700000002.7"})
        renderer = SlackRenderer()
        target = _slack_target("C123")

        # Web user — actor.id is a UUID string, no "slack:" prefix.
        web_user_actor = ActorRef.user(
            "550e8400-e29b-41d4-a716-446655440000",
            display_name="Alice",
        )
        ev = _new_message_event(
            role="user",
            content="hi from web",
            actor=web_user_actor,
        )

        receipt = await renderer.render(ev, target)

        assert receipt.success is True
        assert receipt.skip_reason is None
        assert len(fake_http.calls) == 1
        assert fake_http.calls[0]["body"]["username"] == "Alice"

    async def test_user_message_never_updates_thinking_placeholder(self, fake_http):
        """Regression: the user's NEW_MESSAGE shares correlation_id=turn_id
        with the bot's thinking placeholder. Before this guard the user
        message hit the placeholder-update path and chat.update'd over a
        message already branded with bot_attribution — Slack's chat.update
        ignores username/icon, so the user's text surfaced as the bot
        (and the message carried an '(edited)' stamp). User messages must
        always post fresh."""
        fake_http.set_response({"ok": True, "ts": "1700000002.8"})
        renderer = SlackRenderer()
        target = _slack_target("C123")

        turn_id = uuid.uuid4()
        ctx = slack_render_contexts.get_or_create(
            "C123", str(turn_id), bot_id="test-bot"
        )
        ctx.thinking_ts = "1700000000.777"
        ctx.thinking_channel = "C123"

        web_user_actor = ActorRef.user(
            "550e8400-e29b-41d4-a716-446655440000",
            display_name="Michael",
        )
        ev = _new_message_event(
            role="user",
            content="hey rolland, can you get_weather?",
            actor=web_user_actor,
            correlation_id=turn_id,
        )

        receipt = await renderer.render(ev, target)

        assert receipt.success is True
        assert len(fake_http.calls) == 1
        call = fake_http.calls[0]
        assert call["url"] == "https://slack.com/api/chat.postMessage"
        assert call["body"]["username"] == "Michael"
        # Placeholder context must survive — it's the bot's response slot
        # and TURN_ENDED still needs it to finalize the reply.
        assert slack_render_contexts.get("C123", str(turn_id)) is ctx
        assert ctx.thinking_ts == "1700000000.777"

    async def test_no_dedup_state_held_across_calls(self, fake_http):
        """The renderer no longer carries a per-instance dedup LRU.

        NEW_MESSAGE is now outbox-durable
        (``ChannelEventKind.is_outbox_durable``) — the bus path
        (``IntegrationDispatcherTask.subscribe_all``) short-circuits
        these kinds in ``_dispatch``, so the renderer is only ever
        invoked once per (msg_id, target) by the outbox drainer.
        Cross-path dedup state is therefore unnecessary and the
        ``_posted_set`` / ``_posted_order`` LRU was deleted.

        This test asserts the deletion is real: a renderer instance
        carries no dedup attributes, and rendering the same event
        twice (the way you'd simulate a buggy double-delivery) posts
        twice — which is the correct contract once the outbox is the
        single delivery path."""
        fake_http.set_response({"ok": True, "ts": "1700000002.5"})
        renderer = SlackRenderer()
        target = _slack_target("C123")

        assert not hasattr(renderer, "_posted_set")
        assert not hasattr(renderer, "_posted_order")

        msg_id = uuid.uuid4()
        cid = uuid.uuid4()
        ev = _new_message_event(
            role="user", content="hi from web", channel_id=cid, msg_id=msg_id,
        )

        r1 = await renderer.render(ev, target)
        r2 = await renderer.render(ev, target)

        assert r1.success is True
        assert r1.skip_reason is None
        assert r2.success is True
        assert r2.skip_reason is None
        # Both calls hit the API — there's no per-renderer dedup
        # protecting against caller bugs anymore. Cross-path dedup is
        # the outbox drainer's responsibility (via the kind check).
        assert len(fake_http.calls) == 2


# ---------------------------------------------------------------------------
# APPROVAL_REQUESTED — Block Kit posts
# ---------------------------------------------------------------------------


class TestApprovalRequested:
    async def test_tool_approval_posts_block_kit(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000003.0"})
        # Stub build_suggestions so we don't depend on its real
        # signature here.
        with patch(
            "app.services.approval_suggestions.build_suggestions",
            return_value=[],
        ):
            renderer = SlackRenderer()
            receipt = await renderer.render(_approval_event(), _slack_target("C123"))

        assert receipt.success is True
        body = fake_http.calls[0]["body"]
        assert "blocks" in body
        # Three primary buttons: Allow / Approve / Deny.
        action_blocks = [b for b in body["blocks"] if b["type"] == "actions"]
        assert any(
            any(el["action_id"] == "approve_tool_call" for el in b["elements"])
            for b in action_blocks
        )

    async def test_capability_approval_uses_capability_blocks(self, fake_http):
        fake_http.set_response({"ok": True, "ts": "1700000003.5"})
        cap = {
            "id": "cap-1",
            "name": "WebSearch",
            "description": "Search the web",
            "tools_count": 2,
            "skills_count": 1,
        }
        renderer = SlackRenderer()
        receipt = await renderer.render(
            _approval_event(capability=cap), _slack_target("C123"),
        )

        assert receipt.success is True
        body = fake_http.calls[0]["body"]
        # Capability text appears in the header section.
        first_section = next(b for b in body["blocks"] if b["type"] == "section")
        assert "WebSearch" in first_section["text"]["text"]
        assert "Capability activation" in first_section["text"]["text"]


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
