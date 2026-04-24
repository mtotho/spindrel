"""Phase F — DiscordRenderer unit tests.

Mirror of ``tests/unit/test_slack_renderer.py``. The two renderers
share the same coalesce/safety-pass shape so we exercise the same
critical path: token accumulation, debounce window, force-flush on
tool start, final TURN_ENDED edit, error rendering.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.domain.actor import ActorRef
from app.domain.capability import Capability
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.dispatch_target import NoneTarget
from integrations.discord.target import DiscordTarget
from app.domain.message import Message as DomainMessage
from app.domain.payloads import (
    ApprovalRequestedPayload,
    MessagePayload,
    TurnEndedPayload,
    TurnStartedPayload,
    TurnStreamTokenPayload,
    TurnStreamToolStartPayload,
)
from app.integrations import renderer_registry
from integrations.discord import renderer as discord_renderer_mod
from integrations.discord.renderer import (
    STREAM_FLUSH_INTERVAL,
    DiscordRenderer,
    discord_render_contexts,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_state():
    discord_render_contexts.reset()
    discord_renderer_mod._register()  # idempotent re-register
    yield
    discord_render_contexts.reset()


@pytest.fixture
def fake_http():
    """Replace ``discord_renderer_mod._http`` with a request-recording mock."""
    class FakeHTTP:
        def __init__(self):
            self.calls: list[dict] = []
            self._next_data: dict = {"id": "999"}
            self._next_status: int = 200

        def set_response(self, data: dict, *, status_code: int = 200):
            self._next_data = data
            self._next_status = status_code

        async def request(self, method, url, *, json=None, headers=None):
            self.calls.append({
                "method": method, "url": url, "body": json, "headers": headers,
            })
            response = MagicMock()
            response.status_code = self._next_status
            response.is_success = 200 <= self._next_status < 300
            response.headers = {}
            response.json = MagicMock(return_value=self._next_data)
            return response

    fake = FakeHTTP()
    with patch.object(discord_renderer_mod, "_http", fake):
        yield fake


def _target(channel_id: str = "888") -> DiscordTarget:
    return DiscordTarget(channel_id=channel_id, token="discord-token")


def _turn_started(turn_id: uuid.UUID, bot_id: str = "test-bot") -> ChannelEvent:
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.TURN_STARTED,
        payload=TurnStartedPayload(bot_id=bot_id, turn_id=turn_id, reason="user_message"),
    )


def _stream_token(turn_id: uuid.UUID, delta: str) -> ChannelEvent:
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.TURN_STREAM_TOKEN,
        payload=TurnStreamTokenPayload(bot_id="test-bot", turn_id=turn_id, delta=delta),
    )


def _tool_start(turn_id: uuid.UUID) -> ChannelEvent:
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.TURN_STREAM_TOOL_START,
        payload=TurnStreamToolStartPayload(
            bot_id="test-bot", turn_id=turn_id, tool_name="echo", arguments={},
        ),
    )


def _turn_ended(
    turn_id: uuid.UUID, *, result: str | None = "Done!", error: str | None = None,
) -> ChannelEvent:
    return ChannelEvent(
        channel_id=uuid.uuid4(),
        kind=ChannelEventKind.TURN_ENDED,
        payload=TurnEndedPayload(
            bot_id="test-bot",
            turn_id=turn_id,
            result=result,
            error=error,
            client_actions=[],
        ),
    )


def _new_message(
    content: str = "hi",
    *,
    metadata: dict | None = None,
    correlation_id: str | None = None,
) -> ChannelEvent:
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
                metadata=metadata,
                correlation_id=correlation_id,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Registration & capability declarations
# ---------------------------------------------------------------------------


class TestDiscordRendererRegistration:
    def test_registered_under_discord(self):
        renderer = renderer_registry.get("discord")
        assert renderer is not None
        assert isinstance(renderer, DiscordRenderer)

    def test_capability_set(self):
        assert Capability.STREAMING_EDIT in DiscordRenderer.capabilities
        assert Capability.TEXT in DiscordRenderer.capabilities
        assert Capability.RICH_TOOL_RESULTS in DiscordRenderer.capabilities
        assert Capability.APPROVAL_BUTTONS in DiscordRenderer.capabilities
        # Discord doesn't claim THREADING since the delivery layer
        # doesn't model Discord threads yet.
        assert Capability.THREADING not in DiscordRenderer.capabilities


# ---------------------------------------------------------------------------
# Target validation
# ---------------------------------------------------------------------------


class TestTargetValidation:
    async def test_non_discord_target_fails_non_retryable(self, fake_http):
        renderer = DiscordRenderer()
        receipt = await renderer.render(_turn_started(uuid.uuid4()), NoneTarget())
        assert receipt.success is False
        assert receipt.retryable is False
        assert fake_http.calls == []


# ---------------------------------------------------------------------------
# TURN_STARTED placeholder
# ---------------------------------------------------------------------------


class TestTurnStarted:
    async def test_posts_thinking_placeholder(self, fake_http):
        fake_http.set_response({"id": "msg-1"})
        renderer = DiscordRenderer()
        turn_id = uuid.uuid4()

        receipt = await renderer.render(_turn_started(turn_id), _target("888"))

        assert receipt.success is True
        assert receipt.external_id == "msg-1"
        assert len(fake_http.calls) == 1
        call = fake_http.calls[0]
        assert call["method"] == "POST"
        assert "/channels/888/messages" in call["url"]
        assert "thinking" in call["body"]["content"].lower()

    async def test_idempotent_for_same_turn(self, fake_http):
        fake_http.set_response({"id": "msg-1"})
        renderer = DiscordRenderer()
        turn_id = uuid.uuid4()
        target = _target("888")

        await renderer.render(_turn_started(turn_id), target)
        await renderer.render(_turn_started(turn_id), target)

        assert len(fake_http.calls) == 1


# ---------------------------------------------------------------------------
# Streaming coalesce
# ---------------------------------------------------------------------------


class TestStreamingCoalesce:
    async def test_first_token_after_window_calls_patch(self, fake_http):
        fake_http.set_response({"id": "msg-1"})
        renderer = DiscordRenderer()
        turn_id = uuid.uuid4()
        target = _target("888")

        await renderer.render(_turn_started(turn_id), target)
        ctx = discord_render_contexts.get("888", str(turn_id))
        ctx.last_flush_at = time.monotonic() - (STREAM_FLUSH_INTERVAL + 0.1)

        await renderer.render(_stream_token(turn_id, "hello"), target)

        assert len(fake_http.calls) == 2
        edit = fake_http.calls[1]
        assert edit["method"] == "PATCH"
        assert "msg-1" in edit["url"]
        assert "hello" in edit["body"]["content"]

    async def test_tokens_in_window_buffer_only(self, fake_http):
        fake_http.set_response({"id": "msg-1"})
        renderer = DiscordRenderer()
        turn_id = uuid.uuid4()
        target = _target("888")

        await renderer.render(_turn_started(turn_id), target)
        ctx = discord_render_contexts.get("888", str(turn_id))
        ctx.last_flush_at = time.monotonic()

        for delta in ("a", "b", "c"):
            await renderer.render(_stream_token(turn_id, delta), target)

        assert len(fake_http.calls) == 1  # only the placeholder POST
        assert ctx.accumulated_text == "abc"

    async def test_tool_start_force_flushes(self, fake_http):
        fake_http.set_response({"id": "msg-1"})
        renderer = DiscordRenderer()
        turn_id = uuid.uuid4()
        target = _target("888")

        await renderer.render(_turn_started(turn_id), target)
        ctx = discord_render_contexts.get("888", str(turn_id))
        ctx.last_flush_at = time.monotonic()
        await renderer.render(_stream_token(turn_id, "draft"), target)
        assert len(fake_http.calls) == 1

        await renderer.render(_tool_start(turn_id), target)
        assert len(fake_http.calls) == 2
        assert fake_http.calls[1]["method"] == "PATCH"


# ---------------------------------------------------------------------------
# TURN_ENDED final edit
# ---------------------------------------------------------------------------


class TestTurnEnded:
    async def test_updates_placeholder_with_final(self, fake_http):
        fake_http.set_response({"id": "msg-1"})
        renderer = DiscordRenderer()
        turn_id = uuid.uuid4()
        target = _target("888")

        await renderer.render(_turn_started(turn_id), target)
        await renderer.render(
            _turn_ended(turn_id, result="Final answer"), target,
        )

        assert len(fake_http.calls) == 2
        final = fake_http.calls[1]
        assert final["method"] == "PATCH"
        assert "Final answer" in final["body"]["content"]

    async def test_renders_error_when_result_empty(self, fake_http):
        fake_http.set_response({"id": "msg-1"})
        renderer = DiscordRenderer()
        turn_id = uuid.uuid4()
        target = _target("888")

        await renderer.render(_turn_started(turn_id), target)
        await renderer.render(
            _turn_ended(turn_id, result=None, error="cancelled"), target,
        )

        final = fake_http.calls[1]
        assert "Agent error" in final["body"]["content"]

    async def test_no_placeholder_skips_delivery(self, fake_http):
        """TURN_ENDED without a placeholder is a no-op — delivery is
        NEW_MESSAGE's job. Posting from TURN_ENDED would duplicate every
        response. See docs/integrations/design.md §Anti-pattern."""
        renderer = DiscordRenderer()
        turn_id = uuid.uuid4()
        target = _target("888")

        receipt = await renderer.render(
            _turn_ended(turn_id, result="standalone"), target,
        )

        assert receipt.success is True
        assert fake_http.calls == []

    async def test_turn_ended_serializes_against_inflight_flush(self, fake_http):
        """Mirror of the Slack regression — DiscordRenderer is invoked
        via both ``subscribe_all`` and the outbox drainer, so the same
        race exists between in-flight ``_do_flush`` PATCH and the final
        TURN_ENDED PATCH against the same message id. ``_handle_turn_ended``
        must acquire ``flush_lock`` before touching the message id.
        """
        fake_http.set_response({"id": "msg-1"})
        renderer = DiscordRenderer()
        turn_id = uuid.uuid4()
        target = _target("888")

        await renderer.render(_turn_started(turn_id), target)
        ctx = discord_render_contexts.get("888", str(turn_id))
        assert ctx is not None

        await ctx.flush_lock.acquire()

        ended_task = asyncio.create_task(
            renderer.render(
                _turn_ended(turn_id, result="Final answer"), target,
            )
        )
        await asyncio.sleep(0.01)
        assert not ended_task.done(), (
            "TURN_ENDED should be waiting on flush_lock, not racing"
        )

        ctx.flush_lock.release()
        receipt = await asyncio.wait_for(ended_task, timeout=1.0)

        assert receipt.success is True
        patch_calls = [c for c in fake_http.calls if c["method"] == "PATCH"]
        assert len(patch_calls) == 1
        assert "Final answer" in patch_calls[0]["body"]["content"]


# ---------------------------------------------------------------------------
# NEW_MESSAGE
# ---------------------------------------------------------------------------


class TestNewMessage:
    async def test_posts_assistant_message(self, fake_http):
        fake_http.set_response({"id": "msg-3"})
        renderer = DiscordRenderer()
        receipt = await renderer.render(_new_message("hi"), _target("888"))
        assert receipt.success is True
        assert len(fake_http.calls) == 1
        assert fake_http.calls[0]["method"] == "POST"

    async def test_full_tool_results_post_discord_embeds(self, fake_http, monkeypatch):
        async def display_mode(_channel_id: str) -> str:
            return "full"

        monkeypatch.setattr(discord_renderer_mod, "_resolve_tool_output_display", display_mode)
        fake_http.set_response({"id": "msg-3"})
        renderer = DiscordRenderer()
        receipt = await renderer.render(
            _new_message(
                "Search complete",
                metadata={
                    "tool_results": [{
                        "tool_name": "web_search",
                        "display_label": "Web search",
                        "content_type": "application/json",
                        "body": '{"answer": "42"}',
                    }],
                },
            ),
            _target("888"),
        )

        assert receipt.success is True
        body = fake_http.calls[0]["body"]
        assert body["content"] == "Search complete"
        assert body["embeds"][0]["title"] == "Web search"
        assert "answer" in body["embeds"][0]["description"]

    async def test_compact_tool_results_append_badges(self, fake_http, monkeypatch):
        async def display_mode(_channel_id: str) -> str:
            return "compact"

        monkeypatch.setattr(discord_renderer_mod, "_resolve_tool_output_display", display_mode)
        fake_http.set_response({"id": "msg-3"})
        renderer = DiscordRenderer()
        await renderer.render(
            _new_message(
                "Done",
                metadata={
                    "tool_results": [{
                        "tool_name": "web_search",
                        "display_label": "Web search",
                        "content_type": "application/json",
                        "body": '{"answer": "42"}',
                    }],
                },
            ),
            _target("888"),
        )

        body = fake_http.calls[0]["body"]
        assert "Tools: `web_search` - Web search" in body["content"]
        assert "embeds" not in body


# ---------------------------------------------------------------------------
# APPROVAL_REQUESTED
# ---------------------------------------------------------------------------


class TestApprovalRequested:
    async def test_posts_embed_with_components(self, fake_http):
        fake_http.set_response({"id": "msg-4"})
        renderer = DiscordRenderer()
        receipt = await renderer.render(
            ChannelEvent(
                channel_id=uuid.uuid4(),
                kind=ChannelEventKind.APPROVAL_REQUESTED,
                payload=ApprovalRequestedPayload(
                    approval_id="appr-1",
                    bot_id="test-bot",
                    tool_name="run_thing",
                    arguments={"x": 1},
                    reason="Policy gate",
                ),
            ),
            _target("888"),
        )
        assert receipt.success is True
        body = fake_http.calls[0]["body"]
        assert "embeds" in body
        assert "components" in body
        # Three buttons: allow / approve / deny
        custom_ids = [
            comp["custom_id"]
            for action_row in body["components"]
            for comp in action_row["components"]
        ]
        assert any(cid.startswith("aa:") for cid in custom_ids)
        assert any(cid.startswith("ap:") for cid in custom_ids)
        assert any(cid.startswith("dn:") for cid in custom_ids)


# ---------------------------------------------------------------------------
# Discord 429 + 5xx handling
# ---------------------------------------------------------------------------


class TestDiscordErrorHandling:
    async def test_429_returns_retryable(self, fake_http):
        # Patch the response status; 429 path goes through `_call`
        # which reads response.status_code. We need a tweaked fake_http
        # response object that exposes a `headers` mapping for Retry-After.
        renderer = DiscordRenderer()

        class _FakeResp:
            status_code = 429
            is_success = False
            headers = {"Retry-After": "2"}

            def json(self_inner):
                return {}

        async def _request(method, url, *, json=None, headers=None):
            fake_http.calls.append({
                "method": method, "url": url, "body": json, "headers": headers,
            })
            return _FakeResp()

        with patch.object(discord_renderer_mod._http, "request", _request):
            receipt = await renderer.render(
                _turn_started(uuid.uuid4()), _target("888"),
            )

        assert receipt.success is False
        assert receipt.retryable is True
        assert "429" in (receipt.error or "")
