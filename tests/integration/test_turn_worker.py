"""Phase E — turn_worker drives an agent run and publishes typed events.

These tests stub ``run_stream`` so we can assert exactly which
``ChannelEvent`` kinds the worker publishes for a given event sequence.
The full chat → outbox → drainer → renderer flow lives in
``test_outbox_drainer_smoke.py``.
"""
import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig
from app.domain.channel_events import ChannelEventKind
from app.services import turn_worker
from app.services.turn_context import BotContext
from app.schemas.chat import ChatRequest
from app.services import session_locks
from app.services.channel_events import _next_seq, _replay_buffer
from app.services.turn_worker import run_turn
from app.services.turns import TurnHandle

pytestmark = pytest.mark.asyncio


def _bot() -> BotConfig:
    return BotConfig(
        id="test-bot",
        name="Test Bot",
        model="test/model",
        system_prompt="You are a test bot.",
        memory=MemoryConfig(enabled=False),
    )


def _empty_ctx() -> BotContext:
    return BotContext(
        messages=[],
        system_preamble=None,
        model_override=None,
        provider_id_override=None,
        raw_snapshot=[],
        extracted_user_prompt="",
        is_primary=True,
    )


def _handle() -> TurnHandle:
    return TurnHandle(
        session_id=uuid.uuid4(),
        channel_id=uuid.uuid4(),
        turn_id=uuid.uuid4(),
    )


def _bus_kinds_for(channel_id: uuid.UUID) -> list[str]:
    """Return the ChannelEventKind values that landed on the bus for a channel."""
    return [ev.kind.value for ev in _replay_buffer.get(channel_id, [])]


@pytest.fixture(autouse=True)
def _reset_bus_state():
    """Wipe the in-memory bus between tests so seq counts and replay
    buffers don't leak across tests."""
    _next_seq.clear()
    _replay_buffer.clear()
    yield
    _next_seq.clear()
    _replay_buffer.clear()


@pytest.fixture(autouse=True)
def _mock_db_and_persist():
    """Stub the DB session, persist_turn, and member-bot fanout — we only
    care about the bus contract here."""
    with (
        patch("app.services.turn_worker.persist_turn", new_callable=AsyncMock),
        patch("app.services.turn_worker.maybe_compact"),
        patch(
            "app.services.turn_worker._persist_and_publish_user_message",
            new_callable=AsyncMock,
            return_value=uuid.uuid4(),
        ),
        patch("app.services.turn_worker._detect_member_mentions",
              new_callable=AsyncMock, return_value=[]),
        patch("app.services.turn_worker._trigger_member_bot_replies",
              new_callable=AsyncMock),
        patch("app.services.turn_worker.run_turn_supervisors",
              new_callable=AsyncMock),
        patch("app.services.turn_worker.set_agent_context"),
    ):
        yield


async def _drive_turn(
    events_to_yield: list[dict],
    *,
    att_payload: list[dict] | None = None,
    stream_kwargs: dict | None = None,
) -> TurnHandle:
    handle = _handle()
    session_locks.acquire(handle.session_id)

    async def _fake_stream(*args, **kwargs):
        if stream_kwargs is not None:
            stream_kwargs.update(kwargs)
        for ev in events_to_yield:
            yield ev

    with patch("app.services.turn_worker.run_stream", side_effect=_fake_stream):
        await run_turn(
            handle,
            bot=_bot(),
            primary_bot_id="test-bot",
            messages=[],
            user_message="hi",
            ctx=_empty_ctx(),
            req=ChatRequest(message="hi", bot_id="test-bot"),
            user=None,
            audio_data=None,
            audio_format=None,
            att_payload=att_payload,
        )
    return handle


class TestTurnWorker:
    async def test_publishes_turn_started_and_turn_ended(self):
        handle = await _drive_turn([
            {"type": "response", "text": "done"},
        ])
        kinds = _bus_kinds_for(handle.channel_id)
        assert kinds[0] == ChannelEventKind.TURN_STARTED.value
        assert kinds[-1] == ChannelEventKind.TURN_ENDED.value

    async def test_attachment_turn_reaches_run_stream_without_pre_persist_crash(self):
        attachment = {"id": "att-1", "filename": "plan.txt"}
        stream_kwargs: dict = {}

        handle = await _drive_turn(
            [{"type": "response", "text": "done"}],
            att_payload=[attachment],
            stream_kwargs=stream_kwargs,
        )

        assert stream_kwargs["attachments"] == [attachment]
        ended_events = [
            ev for ev in _replay_buffer.get(handle.channel_id, [])
            if ev.kind is ChannelEventKind.TURN_ENDED
        ]
        assert len(ended_events) == 1
        assert ended_events[0].payload.error is None

    async def test_harness_branch_forwards_attachments_to_runtime_host(self):
        attachment = {"id": "att-1", "filename": "plan.txt"}
        captured: dict = {}

        async def _fake_harness_turn(**kwargs):
            captured.update(kwargs)
            return "done", None

        bot = _bot()
        bot.harness_runtime = "claude-code"
        scope = turn_worker._TurnScope(
            session_id=uuid.uuid4(),
            channel_id=uuid.uuid4(),
            bus_key=uuid.uuid4(),
            turn_id=uuid.uuid4(),
            session_scoped=False,
            correlation_id=uuid.uuid4(),
        )
        state = turn_worker._TurnRunState()

        with patch("app.services.turn_worker._run_harness_turn", side_effect=_fake_harness_turn):
            handled = await turn_worker._run_harness_branch_if_needed(
                scope,
                state,
                bot=bot,
                req=ChatRequest(message="hi", bot_id=bot.id),
                user_message="hi",
                att_payload=[attachment],
            )

        assert handled is True
        assert captured["harness_attachments"] == (attachment,)
        assert state.response_text == "done"
        assert state.error_text is None

    async def test_text_delta_maps_to_turn_stream_token(self):
        handle = await _drive_turn([
            {"type": "text_delta", "delta": "hello"},
            {"type": "text_delta", "delta": " world"},
            {"type": "response", "text": "hello world"},
        ])
        kinds = _bus_kinds_for(handle.channel_id)
        token_kinds = [k for k in kinds if k == ChannelEventKind.TURN_STREAM_TOKEN.value]
        assert len(token_kinds) == 2

    async def test_tool_start_and_result_publish(self):
        handle = await _drive_turn([
            {"type": "tool_start", "tool": "echo", "args": {"x": 1}},
            {"type": "tool_result", "tool": "echo", "result": "1"},
            {"type": "response", "text": "ok"},
        ])
        kinds = _bus_kinds_for(handle.channel_id)
        assert ChannelEventKind.TURN_STREAM_TOOL_START.value in kinds
        assert ChannelEventKind.TURN_STREAM_TOOL_RESULT.value in kinds

    async def test_session_lock_released_on_success(self):
        handle = await _drive_turn([{"type": "response", "text": "ok"}])
        assert not session_locks.is_active(handle.session_id)

    async def test_session_lock_released_on_run_stream_exception(self):
        handle = _handle()
        session_locks.acquire(handle.session_id)

        async def _boom(*args, **kwargs):
            raise RuntimeError("agent loop blew up")
            yield  # pragma: no cover

        with (
            patch("app.services.turn_worker.run_stream", side_effect=_boom),
            patch("app.services.turn_worker.persist_turn", new_callable=AsyncMock) as mock_persist,
        ):
            await run_turn(
                handle,
                bot=_bot(),
                primary_bot_id="test-bot",
                messages=[],
                user_message="hi",
                ctx=_empty_ctx(),
                req=ChatRequest(message="hi", bot_id="test-bot"),
                user=None,
                audio_data=None,
                audio_format=None,
                att_payload=None,
            )

        assert not session_locks.is_active(handle.session_id)
        mock_persist.assert_awaited_once()
        persisted_messages = mock_persist.await_args.args[3]
        assistant = next(m for m in persisted_messages if m.get("role") == "assistant")
        assert assistant["_turn_error"] is True
        assert assistant["_turn_error_message"] == "RuntimeError: agent loop blew up"
        assert "The turn failed before producing a response." in assistant["content"]
        # TURN_ENDED still published with error info
        kinds = _bus_kinds_for(handle.channel_id)
        assert ChannelEventKind.TURN_ENDED.value in kinds

    async def test_run_stream_exception_persists_partial_streamed_text_with_error(self):
        handle = _handle()
        session_locks.acquire(handle.session_id)

        async def _stream(*args, **kwargs):
            yield {"type": "text_delta", "delta": "partial answer"}
            raise RuntimeError("context window exceeded")

        with (
            patch("app.services.turn_worker.run_stream", side_effect=_stream),
            patch("app.services.turn_worker.persist_turn", new_callable=AsyncMock) as mock_persist,
        ):
            await run_turn(
                handle,
                bot=_bot(),
                primary_bot_id="test-bot",
                messages=[],
                user_message="hi",
                ctx=_empty_ctx(),
                req=ChatRequest(message="hi", bot_id="test-bot"),
                user=None,
                audio_data=None,
                audio_format=None,
                att_payload=None,
            )

        mock_persist.assert_awaited_once()
        persisted_messages = mock_persist.await_args.args[3]
        assistant = next(m for m in persisted_messages if m.get("role") == "assistant")
        assert assistant["_turn_error"] is True
        assert assistant["_turn_error_message"] == "RuntimeError: context window exceeded"
        assert assistant["content"].startswith("partial answer")
        assert "[Turn failed: RuntimeError: context window exceeded]" in assistant["content"]

    async def test_cancelled_turn_still_persists_stop_markers(self):
        """Regression: Phase E initially guarded persist_turn with
        ``if not was_cancelled``, which silently dropped the [STOP] /
        [Cancelled by user] markers. The legacy event_generator persisted
        them unconditionally, and so should the new worker.
        """
        handle = _handle()
        session_locks.acquire(handle.session_id)

        async def _stream(*args, **kwargs):
            yield {"type": "text_delta", "delta": "partial"}
            yield {"type": "cancelled"}

        with (
            patch("app.services.turn_worker.run_stream", side_effect=_stream),
            patch(
                "app.services.turn_worker.persist_turn",
                new_callable=AsyncMock,
            ) as mock_persist,
        ):
            await run_turn(
                handle,
                bot=_bot(),
                primary_bot_id="test-bot",
                messages=[],
                user_message="hi",
                ctx=_empty_ctx(),
                req=ChatRequest(message="hi", bot_id="test-bot"),
                user=None,
                audio_data=None,
                audio_format=None,
                att_payload=None,
            )

        mock_persist.assert_awaited_once()
        # The messages list passed to persist_turn must contain the
        # cancellation markers appended by the worker.
        call_messages = mock_persist.await_args.args[3]
        contents = [m.get("content") for m in call_messages]
        assert "[STOP]" in contents
        assert "[Cancelled by user]" in contents

    async def test_cancelled_turn_publishes_turn_ended_with_error(self):
        """Cancelled turns must publish TURN_ENDED with a non-empty error
        so the UI can distinguish a cancel from an empty graceful turn.
        """
        handle = _handle()
        session_locks.acquire(handle.session_id)

        async def _stream(*args, **kwargs):
            yield {"type": "cancelled"}

        with patch("app.services.turn_worker.run_stream", side_effect=_stream):
            await run_turn(
                handle,
                bot=_bot(),
                primary_bot_id="test-bot",
                messages=[],
                user_message="hi",
                ctx=_empty_ctx(),
                req=ChatRequest(message="hi", bot_id="test-bot"),
                user=None,
                audio_data=None,
                audio_format=None,
                att_payload=None,
            )

        # Find the TURN_ENDED event on the bus and assert it carries an error.
        ended_events = [
            ev for ev in _replay_buffer.get(handle.channel_id, [])
            if ev.kind is ChannelEventKind.TURN_ENDED
        ]
        assert len(ended_events) == 1
        assert ended_events[0].payload.error == "cancelled"

    async def test_turn_ended_carries_error_when_persist_fails_after_response(self):
        """Regression for the Phase F masking bug.

        Phase E published TURN_ENDED with
        ``error=error_text if not response_text else None``, which
        silently swallowed persist_turn / fanout failures whenever the
        agent had already produced a response. The UI saw a green
        turn while the messages were actually lost on disk. The fix
        is to publish ``error=error_text or None`` so result + error
        are independent.
        """
        handle = _handle()
        session_locks.acquire(handle.session_id)

        async def _stream(*args, **kwargs):
            yield {"type": "text_delta", "delta": "all"}
            yield {"type": "response", "text": "all good"}

        async def _persist_boom(*args, **kwargs):
            raise RuntimeError("simulated DB transaction failure")

        with (
            patch("app.services.turn_worker.run_stream", side_effect=_stream),
            patch(
                "app.services.turn_worker.persist_turn",
                new=AsyncMock(side_effect=_persist_boom),
            ),
        ):
            await run_turn(
                handle,
                bot=_bot(),
                primary_bot_id="test-bot",
                messages=[],
                user_message="hi",
                ctx=_empty_ctx(),
                req=ChatRequest(message="hi", bot_id="test-bot"),
                user=None,
                audio_data=None,
                audio_format=None,
                att_payload=None,
            )

        ended_events = [
            ev for ev in _replay_buffer.get(handle.channel_id, [])
            if ev.kind is ChannelEventKind.TURN_ENDED
        ]
        assert len(ended_events) == 1
        # Both fields must be set: the user-facing response is real, AND
        # the renderer / UI must know persistence failed.
        assert ended_events[0].payload.result == "all good"
        assert ended_events[0].payload.error == "persist_turn failed"

    async def test_delegation_post_routes_to_post_child_response(self):
        handle = _handle()
        session_locks.acquire(handle.session_id)

        async def _stream(*args, **kwargs):
            yield {
                "type": "delegation_post",
                "text": "child reply",
                "bot_id": "child-bot",
                "reply_in_thread": False,
            }
            yield {"type": "response", "text": "parent done"}

        with (
            patch("app.services.turn_worker.run_stream", side_effect=_stream),
            patch(
                "app.services.turn_worker._ds.post_child_response",
                new_callable=AsyncMock,
            ) as mock_post,
        ):
            await run_turn(
                handle,
                bot=_bot(),
                primary_bot_id="test-bot",
                messages=[],
                user_message="delegate",
                ctx=_empty_ctx(),
                req=ChatRequest(message="delegate", bot_id="test-bot"),
                user=None,
                audio_data=None,
                audio_format=None,
                att_payload=None,
            )

        mock_post.assert_awaited_once()
        kwargs = mock_post.await_args.kwargs
        assert kwargs["channel_id"] == handle.channel_id
        assert kwargs["text"] == "child reply"
        assert kwargs["bot_id"] == "child-bot"

    async def test_delegation_post_failure_publishes_error_tool_result(self):
        handle = _handle()
        session_locks.acquire(handle.session_id)

        async def _stream(*args, **kwargs):
            yield {
                "type": "delegation_post",
                "text": "child reply",
                "bot_id": "child-bot",
                "reply_in_thread": False,
            }
            yield {"type": "response", "text": "parent done"}

        with (
            patch("app.services.turn_worker.run_stream", side_effect=_stream),
            patch(
                "app.services.turn_worker._ds.post_child_response",
                new=AsyncMock(side_effect=RuntimeError("thread write failed")),
            ),
        ):
            await run_turn(
                handle,
                bot=_bot(),
                primary_bot_id="test-bot",
                messages=[],
                user_message="delegate",
                ctx=_empty_ctx(),
                req=ChatRequest(message="delegate", bot_id="test-bot"),
                user=None,
                audio_data=None,
                audio_format=None,
                att_payload=None,
            )

        error_events = [
            ev for ev in _replay_buffer.get(handle.channel_id, [])
            if (
                ev.kind is ChannelEventKind.TURN_STREAM_TOOL_RESULT
                and ev.payload.tool_name == "delegation_post"
            )
        ]
        assert len(error_events) == 1
        assert error_events[0].payload.is_error is True
        assert "thread write failed" in error_events[0].payload.result_summary

    async def test_stream_metadata_tags_last_assistant_message_before_persist(self):
        handle = _handle()
        session_locks.acquire(handle.session_id)

        async def _stream(messages, *args, **kwargs):
            messages.append({"role": "assistant", "content": "ok"})
            yield {
                "type": "auto_inject",
                "skill_id": "skill:one",
                "skill_name": "Skill One",
                "similarity": 0.91,
                "source": "rag",
            }
            yield {
                "type": "active_skills",
                "skills": [
                    {"skill_id": "skill:loaded", "source": "loaded"},
                    {"skill_id": "skill:auto", "source": "auto"},
                ],
            }
            yield {"type": "llm_retry", "reason": "vision_not_supported"}
            yield {"type": "llm_fallback", "to_model": "fallback/model"}
            yield {"type": "response", "text": "ok"}

        with (
            patch("app.services.turn_worker.run_stream", side_effect=_stream),
            patch("app.services.turn_worker.persist_turn", new_callable=AsyncMock) as mock_persist,
        ):
            await run_turn(
                handle,
                bot=_bot(),
                primary_bot_id="test-bot",
                messages=[],
                user_message="hi",
                ctx=_empty_ctx(),
                req=ChatRequest(message="hi", bot_id="test-bot"),
                user=None,
                audio_data=None,
                audio_format=None,
                att_payload=None,
            )

        persisted_messages = mock_persist.await_args.args[3]
        assistant = next(m for m in persisted_messages if m.get("role") == "assistant")
        assert assistant["_auto_injected_skills"] == [{
            "skill_id": "skill:one",
            "skill_name": "Skill One",
            "similarity": 0.91,
            "source": "rag",
        }]
        assert assistant["_active_skills"] == [
            {"skill_id": "skill:loaded", "source": "loaded"},
        ]
        assert assistant["_skills_in_context"] == [
            {"skill_id": "skill:loaded", "source": "loaded"},
            {"skill_id": "skill:auto", "source": "auto"},
        ]
        assert assistant["_llm_status"] == {
            "retries": 1,
            "fallback_model": "fallback/model",
            "vision_fallback": True,
        }
