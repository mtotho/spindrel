"""BlueBubblesRenderer unit tests.

BB is a non-streaming renderer: ``NEW_MESSAGE`` is the sole text
delivery path. ``TURN_ENDED`` is a no-op (no placeholder to finalize).

Test surface:

- Self-registration via the renderer registry.
- Capability declarations (specifically: STREAMING_EDIT NOT present).
- Target type validation.
- ``TURN_ENDED`` is skipped (delivery contract enforcement).
- ``NEW_MESSAGE`` is the sole delivery path: footer, chunking,
  echo-tracker wiring, echo prevention, internal role filtering.
- ``APPROVAL_REQUESTED`` text-based fallback.
- Silent skips for streaming events.

The renderer is patched at ``send_text`` so we can record what would
have hit the BB REST API and at ``shared_tracker`` so we can verify
the echo-tracking calls happen BEFORE the network send.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.actor import ActorRef
from app.domain.capability import Capability
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.dispatch_target import NoneTarget
from app.domain.message import Message as DomainMessage
from app.domain.payloads import (
    ApprovalRequestedPayload,
    AttachmentDeletedPayload,
    MessagePayload,
    TurnEndedPayload,
    TurnStartedPayload,
    TurnStreamTokenPayload,
)
from app.integrations import renderer_registry
from integrations.bluebubbles import renderer as bb_renderer_mod
from integrations.bluebubbles.renderer import (
    BlueBubblesRenderer,
    _split_text,
)
from integrations.bluebubbles.target import BlueBubblesTarget

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _re_register_renderer():
    """Re-register the BB renderer in case a previous test cleared the registry."""
    bb_renderer_mod._register()
    yield


@pytest.fixture
def fake_send_text():
    """Patch ``send_text`` and record every call's arguments.

    Tests assert on the recorded payloads (chat_guid, text body, method
    override, etc.) and configure the next return value to drive the
    success / failure paths.
    """
    calls: list[dict] = []
    return_value: list[dict | None] = [{"ok": True}]

    async def _fake(client, server_url, password, chat_guid, text, *,
                    temp_guid=None, method=None):
        calls.append({
            "server_url": server_url,
            "password": password,
            "chat_guid": chat_guid,
            "text": text,
            "temp_guid": temp_guid,
            "method": method,
        })
        return return_value[0]

    with patch.object(bb_renderer_mod, "send_text", side_effect=_fake) as mock:
        # Stash a setter so tests can change the return value mid-test.
        mock.calls = calls
        mock.set_return = lambda v: return_value.__setitem__(0, v)
        yield mock


@pytest.fixture
def fake_tracker():
    """Patch the shared echo tracker so we can assert track ordering.

    The renderer MUST call ``track_sent`` + ``save_to_db`` BEFORE the
    network send so an inbound webhook arriving in the same instant
    sees the bot's reply as an echo, not a human input. We verify
    ordering by recording the absolute call sequence across both the
    tracker and ``send_text``.
    """
    sequence: list[str] = []

    fake = MagicMock()
    fake.track_sent = MagicMock(side_effect=lambda *a, **kw: sequence.append("track"))
    fake.save_to_db = AsyncMock(side_effect=lambda: sequence.append("save"))

    with patch.object(bb_renderer_mod, "shared_tracker", fake):
        fake.sequence = sequence
        yield fake


def _target(chat_guid: str = "iMessage;-;+15551234", **kwargs) -> BlueBubblesTarget:
    return BlueBubblesTarget(
        chat_guid=chat_guid,
        server_url="http://bb.example.com",
        password="hunter2",
        **kwargs,
    )


def _turn_ended(*, result: str | None = "All done.", error: str | None = None) -> ChannelEvent:
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.TURN_ENDED,
        payload=TurnEndedPayload(
            bot_id="test-bot",
            turn_id=uuid.uuid4(),
            result=result,
            error=error,
            client_actions=[],
        ),
    )


def _new_message(content: str = "hi") -> ChannelEvent:
    cid = uuid.uuid4()
    return ChannelEvent(
        channel_id=cid,
        kind=ChannelEventKind.NEW_MESSAGE,
        payload=MessagePayload(
            message=DomainMessage(
                id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                role="assistant",
                content=content,
                created_at=datetime.now(timezone.utc),
                actor=ActorRef.bot("test-bot"),
                channel_id=cid,
            ),
        ),
    )


def _approval(approval_id: str = "appr-1") -> ChannelEvent:
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.APPROVAL_REQUESTED,
        payload=ApprovalRequestedPayload(
            approval_id=approval_id,
            bot_id="test-bot",
            tool_name="run_command",
            arguments={"cmd": "ls -la"},
            reason="Policy requires approval",
            capability=None,
        ),
    )


# ---------------------------------------------------------------------------
# Registration & capability declarations
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_registered_under_bluebubbles(self):
        renderer = renderer_registry.get("bluebubbles")
        assert renderer is not None
        assert isinstance(renderer, BlueBubblesRenderer)

    def test_capability_set_excludes_streaming_edit(self):
        # iMessage has no message edit API. STREAMING_EDIT must NOT be
        # declared so the drainer's capability gating skips token events
        # silently instead of dispatching them to a renderer that has
        # nothing to do with them.
        assert Capability.STREAMING_EDIT not in BlueBubblesRenderer.capabilities
        assert Capability.RICH_TEXT not in BlueBubblesRenderer.capabilities
        assert Capability.INLINE_BUTTONS not in BlueBubblesRenderer.capabilities

    def test_capability_set_includes_text_and_approvals(self):
        assert Capability.TEXT in BlueBubblesRenderer.capabilities
        assert Capability.APPROVAL_BUTTONS in BlueBubblesRenderer.capabilities
        assert Capability.MENTIONS in BlueBubblesRenderer.capabilities


# ---------------------------------------------------------------------------
# Target validation
# ---------------------------------------------------------------------------


class TestTargetValidation:
    async def test_non_bluebubbles_target_fails_non_retryable(self, fake_send_text, fake_tracker):
        renderer = BlueBubblesRenderer()
        receipt = await renderer.render(_turn_ended(), NoneTarget())
        assert receipt.success is False
        assert receipt.retryable is False
        assert "non-bluebubbles" in (receipt.error or "")
        assert fake_send_text.calls == []


# ---------------------------------------------------------------------------
# TURN_ENDED — no-op (delivery contract)
# ---------------------------------------------------------------------------


class TestTurnEnded:
    async def test_turn_ended_skipped_no_text_sent(self, fake_send_text, fake_tracker):
        """TURN_ENDED must NOT send messages — that's NEW_MESSAGE's job.

        iMessage has no edit/update API, so posting from both TURN_ENDED
        and NEW_MESSAGE would duplicate every response. See
        docs/integrations/design.md §Anti-pattern.
        """
        renderer = BlueBubblesRenderer()
        receipt = await renderer.render(
            _turn_ended(result="All tests pass."), _target(),
        )
        assert receipt.success is True
        assert "NEW_MESSAGE" in (receipt.skip_reason or "")
        assert fake_send_text.calls == []

    async def test_turn_ended_with_error_still_skipped(self, fake_send_text, fake_tracker):
        """Even error responses must flow through NEW_MESSAGE, not TURN_ENDED."""
        renderer = BlueBubblesRenderer()
        receipt = await renderer.render(
            _turn_ended(result=None, error="rate limited"), _target(),
        )
        assert receipt.success is True
        assert "NEW_MESSAGE" in (receipt.skip_reason or "")
        assert fake_send_text.calls == []


# ---------------------------------------------------------------------------
# Echo-tracker ordering — load-bearing (on NEW_MESSAGE path)
# ---------------------------------------------------------------------------


class TestEchoTrackerOrdering:
    async def test_track_and_save_run_before_send(self, fake_send_text, fake_tracker):
        """``track_sent`` + ``save_to_db`` MUST run before ``send_text``.

        If they ran after, an inbound webhook arriving while the send
        is in flight would see the bot's reply as a human input and
        re-trigger the agent. The shared echo tracker's
        ``is_own_content`` is the primary defense and only sees what's
        already been recorded.
        """
        renderer = BlueBubblesRenderer()

        # Wrap send_text so we can record its position in the sequence.
        original = fake_send_text.side_effect

        async def _wrapped(*args, **kwargs):
            fake_tracker.sequence.append("send")
            return await original(*args, **kwargs)

        fake_send_text.side_effect = _wrapped

        await renderer.render(_new_message("hello"), _target())

        # The sequence MUST be: track → save → send (per chunk).
        assert fake_tracker.sequence == ["track", "save", "send"]


# ---------------------------------------------------------------------------
# NEW_MESSAGE — passive / mirror / member-bot fanout
# ---------------------------------------------------------------------------


def _new_message_user(content: str = "hi", source: str = "bluebubbles") -> ChannelEvent:
    """NEW_MESSAGE with role=user — simulates a user message echoed back via outbox."""
    cid = uuid.uuid4()
    return ChannelEvent(
        channel_id=cid,
        kind=ChannelEventKind.NEW_MESSAGE,
        payload=MessagePayload(
            message=DomainMessage(
                id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                role="user",
                content=content,
                created_at=datetime.now(timezone.utc),
                actor=ActorRef.user(f"bb:+15551234"),
                metadata={"source": source},
                channel_id=cid,
            ),
        ),
    )


def _new_message_internal(role: str = "tool") -> ChannelEvent:
    """NEW_MESSAGE with an internal role (tool/system)."""
    cid = uuid.uuid4()
    return ChannelEvent(
        channel_id=cid,
        kind=ChannelEventKind.NEW_MESSAGE,
        payload=MessagePayload(
            message=DomainMessage(
                id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                role=role,
                content='{"ok": true}',
                created_at=datetime.now(timezone.utc),
                actor=ActorRef.bot("test-bot"),
                channel_id=cid,
            ),
        ),
    )


class TestNewMessage:
    async def test_posts_message_content(self, fake_send_text, fake_tracker):
        renderer = BlueBubblesRenderer()
        receipt = await renderer.render(_new_message("hello there"), _target())
        assert receipt.success is True
        assert fake_send_text.calls[0]["text"] == "hello there"

    async def test_empty_content_skipped(self, fake_send_text, fake_tracker):
        renderer = BlueBubblesRenderer()
        receipt = await renderer.render(_new_message(""), _target())
        assert receipt.success is True
        assert "empty" in (receipt.skip_reason or "")
        assert fake_send_text.calls == []

    async def test_text_footer_applied(self, fake_send_text, fake_tracker):
        renderer = BlueBubblesRenderer()
        target = _target(text_footer="-- bot")
        await renderer.render(_new_message("hi"), target)
        assert fake_send_text.calls[0]["text"] == "hi\n-- bot"

    async def test_own_origin_user_message_skipped(self, fake_send_text, fake_tracker):
        """User messages originating from BB must NOT be echoed back to iMessage.

        Without this guard, every inbound iMessage gets re-sent as a bot
        reply because store_passive_message enqueues a NEW_MESSAGE in the
        outbox, and the drainer delivers it right back to this renderer.
        """
        renderer = BlueBubblesRenderer()
        receipt = await renderer.render(_new_message_user("hello", source="bluebubbles"), _target())
        assert receipt.success is True
        assert "echo prevention" in (receipt.skip_reason or "")
        assert fake_send_text.calls == []

    async def test_cross_origin_user_message_delivered(self, fake_send_text, fake_tracker):
        """User messages from OTHER sources (e.g. web UI) SHOULD be mirrored."""
        renderer = BlueBubblesRenderer()
        receipt = await renderer.render(_new_message_user("hello", source="web"), _target())
        assert receipt.success is True
        assert fake_send_text.calls[0]["text"] == "hello"

    async def test_tool_role_skipped(self, fake_send_text, fake_tracker):
        """Tool-result messages should never be sent to iMessage."""
        renderer = BlueBubblesRenderer()
        receipt = await renderer.render(_new_message_internal("tool"), _target())
        assert receipt.success is True
        assert "internal role" in (receipt.skip_reason or "")
        assert fake_send_text.calls == []

    async def test_system_role_skipped(self, fake_send_text, fake_tracker):
        """System messages should never be sent to iMessage."""
        renderer = BlueBubblesRenderer()
        receipt = await renderer.render(_new_message_internal("system"), _target())
        assert receipt.success is True
        assert "internal role" in (receipt.skip_reason or "")
        assert fake_send_text.calls == []

    async def test_send_method_threaded_through(self, fake_send_text, fake_tracker):
        renderer = BlueBubblesRenderer()
        target = _target(send_method="apple-script")
        await renderer.render(_new_message("hello"), target)
        assert fake_send_text.calls[0]["method"] == "apple-script"

    async def test_text_footer_appended_before_chunking(self, fake_send_text, fake_tracker):
        renderer = BlueBubblesRenderer()
        target = _target(text_footer="-- via Spindrel")
        await renderer.render(_new_message("Hello world."), target)
        assert len(fake_send_text.calls) == 1
        assert fake_send_text.calls[0]["text"] == "Hello world.\n-- via Spindrel"

    async def test_long_text_chunks(self, fake_send_text, fake_tracker):
        renderer = BlueBubblesRenderer()
        long = "x" * 25_000  # > _MAX_MSG_LEN (20_000)
        await renderer.render(_new_message(long), _target())
        assert len(fake_send_text.calls) >= 2

    async def test_send_failure_returns_retryable(self, fake_send_text, fake_tracker):
        renderer = BlueBubblesRenderer()
        fake_send_text.set_return(None)
        receipt = await renderer.render(_new_message("hello"), _target())
        assert receipt.success is False
        assert receipt.retryable is True


# ---------------------------------------------------------------------------
# APPROVAL_REQUESTED — text-based fallback (no buttons)
# ---------------------------------------------------------------------------


class TestApprovalRequested:
    async def test_renders_text_approval(self, fake_send_text, fake_tracker):
        renderer = BlueBubblesRenderer()
        receipt = await renderer.render(_approval("appr-42"), _target())
        assert receipt.success is True
        body = fake_send_text.calls[0]["text"]
        assert "appr-42" in body
        assert "run_command" in body
        assert "Policy requires approval" in body
        # Reminder: iMessage has no buttons, the user approves via the web UI.
        assert "web UI" in body


# ---------------------------------------------------------------------------
# Silent skips — events the renderer can't render
# ---------------------------------------------------------------------------


class TestTypingIndicator:
    async def test_turn_started_sends_typing(self, fake_send_text, fake_tracker):
        """TURN_STARTED fires a typing indicator (fire-and-forget)."""
        renderer = BlueBubblesRenderer()
        event = ChannelEvent(
            channel_id=uuid.uuid4(),
            kind=ChannelEventKind.TURN_STARTED,
            payload=TurnStartedPayload(
                bot_id="b", turn_id=uuid.uuid4(), reason="user_message",
            ),
        )
        with patch.object(bb_renderer_mod, "set_typing", new_callable=AsyncMock, return_value=True) as mock_typing:
            receipt = await renderer.render(event, _target())
        assert receipt.success is True
        assert "typing indicator sent" in (receipt.skip_reason or "")
        mock_typing.assert_awaited_once()
        assert fake_send_text.calls == []

    async def test_turn_started_skipped_when_disabled(self, fake_send_text, fake_tracker):
        """TURN_STARTED skips typing when the binding has it disabled."""
        renderer = BlueBubblesRenderer()
        event = ChannelEvent(
            channel_id=uuid.uuid4(),
            kind=ChannelEventKind.TURN_STARTED,
            payload=TurnStartedPayload(
                bot_id="b", turn_id=uuid.uuid4(), reason="user_message",
            ),
        )
        with patch.object(bb_renderer_mod, "set_typing", new_callable=AsyncMock) as mock_typing:
            receipt = await renderer.render(event, _target(typing_indicator=False))
        assert receipt.success is True
        assert "disabled" in (receipt.skip_reason or "")
        mock_typing.assert_not_awaited()


class TestSilentSkips:

    async def test_stream_token_skipped(self, fake_send_text, fake_tracker):
        renderer = BlueBubblesRenderer()
        event = ChannelEvent(
            channel_id=uuid.uuid4(),
            kind=ChannelEventKind.TURN_STREAM_TOKEN,
            payload=TurnStreamTokenPayload(
                bot_id="b", turn_id=uuid.uuid4(), delta="hello",
            ),
        )
        receipt = await renderer.render(event, _target())
        assert receipt.success is True
        assert fake_send_text.calls == []

    async def test_attachment_deleted_skipped(self, fake_send_text, fake_tracker):
        renderer = BlueBubblesRenderer()
        event = ChannelEvent(
            channel_id=uuid.uuid4(),
            kind=ChannelEventKind.ATTACHMENT_DELETED,
            payload=AttachmentDeletedPayload(
                attachment_id=uuid.uuid4(),
                metadata={"slack_file_id": "F123"},
            ),
        )
        receipt = await renderer.render(event, _target())
        assert receipt.success is True
        assert fake_send_text.calls == []


# ---------------------------------------------------------------------------
# delete_attachment — BB has no API, always False
# ---------------------------------------------------------------------------


class TestDeleteAttachment:
    async def test_always_false(self, fake_send_text, fake_tracker):
        renderer = BlueBubblesRenderer()
        ok = await renderer.delete_attachment({"some": "metadata"}, _target())
        assert ok is False


# ---------------------------------------------------------------------------
# _split_text — chunking helper ported from the legacy dispatcher
# ---------------------------------------------------------------------------


class TestSplitText:
    def test_short_text_single_chunk(self):
        chunks = _split_text("hello")
        assert chunks == ["hello"]

    def test_chunks_at_newline_boundary(self):
        text = "x" * 12_000 + "\n" + "y" * 12_000
        chunks = _split_text(text, max_len=20_000)
        assert len(chunks) == 2
        # First chunk includes everything up to the newline.
        assert chunks[0] == "x" * 12_000
        assert chunks[1] == "y" * 12_000

    def test_chunks_at_max_when_no_newline(self):
        text = "z" * 25_000
        chunks = _split_text(text, max_len=20_000)
        assert len(chunks) == 2
        assert len(chunks[0]) == 20_000
        assert len(chunks[1]) == 5_000
