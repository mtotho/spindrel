"""Real-DB coverage of turn_worker.run_turn.

The sibling test file ``test_turn_worker.py`` mocks ``persist_turn`` and
``_persist_and_publish_user_message`` to assert the bus contract in
isolation. Those mocks leave the actual DB-writing paths uncovered —
``run_turn`` could stop persisting messages entirely and those tests would
still pass.

This file pins the persistence contract end-to-end against a real SQLite
engine. Only the external agent loop (``run_stream`` — E.1) and the
member-bot fanout (out of scope) are mocked.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.bots import BotConfig, MemoryConfig
from app.db.models import Bot as BotRow, Channel, Message as MessageRow, Session as SessionRow
from app.domain.channel_events import ChannelEventKind
from app.routers.chat._context import BotContext
from app.routers.chat._schemas import ChatRequest
from app.services import session_locks
from app.services.channel_events import _next_seq, _replay_buffer
from app.services.turn_worker import run_turn
from app.services.turns import TurnHandle
from tests.factories import build_bot, build_channel

pytestmark = pytest.mark.asyncio


TEST_BOT_CFG = BotConfig(
    id="persist-test-bot",
    name="Persist Test Bot",
    model="test/model",
    system_prompt="You are a test bot.",
    memory=MemoryConfig(enabled=False),
)


def _empty_ctx() -> BotContext:
    return BotContext(
        messages=[],
        system_preamble=None,
        model_override=None,
        raw_snapshot=[],
        extracted_user_prompt="",
        is_primary=True,
    )


@pytest.fixture(autouse=True)
def _reset_bus_state():
    _next_seq.clear()
    _replay_buffer.clear()
    yield
    _next_seq.clear()
    _replay_buffer.clear()


@pytest_asyncio.fixture
async def persisted_turn_setup(engine, db_session):
    """Seed the DB with a Bot / Channel / Session and route turn_worker to the
    test engine.

    Returns ``(handle, session_factory)``. The caller uses ``handle`` as the
    turn handle and the fixture patches ``app.services.turn_worker.async_session``
    to point at the test engine so the service's own session blocks hit the
    same DB ``db_session`` reads from.
    """
    bot_row = build_bot(id=TEST_BOT_CFG.id, name=TEST_BOT_CFG.name, model=TEST_BOT_CFG.model)
    db_session.add(bot_row)

    channel = build_channel(bot_id=TEST_BOT_CFG.id)
    db_session.add(channel)

    session = SessionRow(
        id=uuid.uuid4(),
        client_id="test-client",
        bot_id=TEST_BOT_CFG.id,
        channel_id=channel.id,
        created_at=datetime.now(timezone.utc),
        last_active=datetime.now(timezone.utc),
    )
    db_session.add(session)
    await db_session.commit()

    handle = TurnHandle(
        session_id=session.id,
        channel_id=channel.id,
        turn_id=uuid.uuid4(),
    )
    session_locks.acquire(handle.session_id)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with patch.multiple(
        "app.db.engine", async_session=factory
    ), patch(
        "app.services.turn_worker.async_session", factory
    ), patch(
        "app.services.sessions.async_session", factory
    ), patch(
        "app.services.dispatch_resolution.async_session", factory
    ), patch(
        "app.services.turn_worker._detect_member_mentions",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "app.services.turn_worker._trigger_member_bot_replies",
        new_callable=AsyncMock,
    ), patch(
        "app.services.turn_worker.maybe_compact",
    ), patch(
        "app.services.turn_worker.set_agent_context",
    ):
        yield handle


async def _drive(
    handle: TurnHandle,
    events: list[dict],
    *,
    user_message: str = "hi",
    appended_messages: list[dict] | None = None,
) -> None:
    """Run a turn with a stubbed run_stream.

    The real ``run_stream`` (agent loop) mutates the ``messages`` list as it
    generates assistant / tool-call turns. Since we're stubbing it we have to
    simulate that mutation — otherwise ``persist_turn`` sees an empty slice
    and no assistant row lands. ``appended_messages`` is what the real agent
    loop would have appended; default is a single assistant reply matching
    the first ``response`` event's text.
    """
    if appended_messages is None:
        for ev in events:
            if ev.get("type") == "response":
                appended_messages = [{"role": "assistant", "content": ev.get("text", "")}]
                break
        if appended_messages is None:
            appended_messages = []

    async def _fake_stream(messages, *args, **kwargs):
        messages.extend(appended_messages)
        for ev in events:
            yield ev

    with patch("app.services.turn_worker.run_stream", side_effect=_fake_stream):
        await run_turn(
            handle,
            bot=TEST_BOT_CFG,
            primary_bot_id=TEST_BOT_CFG.id,
            messages=[],
            user_message=user_message,
            ctx=_empty_ctx(),
            req=ChatRequest(message=user_message, bot_id=TEST_BOT_CFG.id),
            user=None,
            audio_data=None,
            audio_format=None,
            att_payload=None,
        )


class TestTurnWorkerPersistence:
    async def test_when_run_stream_raises_then_no_assistant_row_persisted(
        self, db_session, persisted_turn_setup
    ):
        handle = persisted_turn_setup

        async def _boom(*args, **kwargs):
            raise RuntimeError("agent loop blew up")
            yield  # pragma: no cover

        with patch("app.services.turn_worker.run_stream", side_effect=_boom):
            await run_turn(
                handle,
                bot=TEST_BOT_CFG,
                primary_bot_id=TEST_BOT_CFG.id,
                messages=[],
                user_message="will fail",
                ctx=_empty_ctx(),
                req=ChatRequest(message="will fail", bot_id=TEST_BOT_CFG.id),
                user=None,
                audio_data=None,
                audio_format=None,
                att_payload=None,
            )

        assistant_rows = (
            await db_session.execute(
                select(MessageRow).where(
                    MessageRow.session_id == handle.session_id,
                    MessageRow.role == "assistant",
                )
            )
        ).scalars().all()
        assert assistant_rows == []
        assert not session_locks.is_active(handle.session_id)

    async def test_when_response_succeeds_then_turn_ended_event_has_no_error(
        self, db_session, persisted_turn_setup
    ):
        handle = persisted_turn_setup

        await _drive(handle, [{"type": "response", "text": "ok"}])

        ended = [
            ev for ev in _replay_buffer.get(handle.channel_id, [])
            if ev.kind is ChannelEventKind.TURN_ENDED
        ]
        assert len(ended) == 1
        assert ended[0].payload.error is None
        assert ended[0].payload.result == "ok"

    async def test_when_session_lock_held_then_released_after_persistence(
        self, db_session, persisted_turn_setup
    ):
        handle = persisted_turn_setup
        assert session_locks.is_active(handle.session_id)

        await _drive(handle, [{"type": "response", "text": "done"}])

        assert not session_locks.is_active(handle.session_id)
