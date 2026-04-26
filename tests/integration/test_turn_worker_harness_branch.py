"""turn_worker.run_turn dispatches to a harness runtime when bot.harness_runtime is set.

Mocks the runtime itself (we trust the bridge's unit tests); pins the
contract that turn_worker correctly:
  - branches early (skips run_stream),
  - calls runtime.start_turn with the right kwargs,
  - persists the assistant message with `metadata.harness`,
  - publishes TURN_STARTED + TURN_ENDED on the bus,
  - writes harness_session_state back to the bots row for resume.
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
from app.db.models import Bot as BotRow, Message as MessageRow, Session as SessionRow
from app.domain.channel_events import ChannelEventKind
from app.routers.chat._context import BotContext
from app.routers.chat._schemas import ChatRequest
from app.services import session_locks
from app.services.agent_harnesses.base import TurnResult
from app.services.channel_events import _next_seq, _replay_buffer
from app.services.turn_worker import run_turn
from app.services.turns import TurnHandle
from tests.factories import build_bot, build_channel

pytestmark = pytest.mark.asyncio


HARNESS_BOT_CFG = BotConfig(
    id="harness-test-bot",
    name="Harness Test Bot",
    model="",
    system_prompt="",
    memory=MemoryConfig(enabled=False),
    harness_runtime="claude-code",
    harness_workdir="/tmp/test-workspace",
    harness_session_state=None,
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


@pytest.fixture(autouse=True)
def _reset_bus_state():
    _next_seq.clear()
    _replay_buffer.clear()
    yield
    _next_seq.clear()
    _replay_buffer.clear()


@pytest_asyncio.fixture
async def harness_setup(engine, db_session):
    bot_row = build_bot(
        id=HARNESS_BOT_CFG.id,
        name=HARNESS_BOT_CFG.name,
        model=HARNESS_BOT_CFG.model or "unused",
    )
    bot_row.harness_runtime = "claude-code"
    bot_row.harness_workdir = "/tmp/test-workspace"
    bot_row.harness_session_state = None
    db_session.add(bot_row)

    channel = build_channel(bot_id=HARNESS_BOT_CFG.id)
    db_session.add(channel)

    session = SessionRow(
        id=uuid.uuid4(),
        client_id="test-client",
        bot_id=HARNESS_BOT_CFG.id,
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
    with patch.multiple("app.db.engine", async_session=factory), patch(
        "app.services.turn_worker.async_session", factory
    ), patch(
        "app.services.sessions.async_session", factory
    ), patch(
        "app.services.dispatch_resolution.async_session", factory
    ), patch(
        "app.agent.recording.async_session", factory
    ), patch(
        "app.services.turn_worker.set_agent_context",
    ), patch(
        "app.services.outbox_publish.enqueue_new_message_for_channel",
        new_callable=AsyncMock,
    ), patch(
        "app.services.outbox_publish.enqueue_new_message_for_thread_session",
        new_callable=AsyncMock,
    ):
        yield handle


async def _drive_harness_turn(
    handle: TurnHandle,
    *,
    runtime_name: str = "claude-code",
    fake_runtime,
    user_message: str = "list files",
    bot_cfg: BotConfig | None = None,
) -> None:
    """Run a turn with a harness driver mocked at the registry level."""
    bot = bot_cfg or HARNESS_BOT_CFG
    with patch.dict(
        "app.services.agent_harnesses.HARNESS_REGISTRY",
        {runtime_name: fake_runtime},
        clear=False,
    ), patch(
        "app.services.turn_worker.get_runtime", return_value=fake_runtime,
    ):
        await run_turn(
            handle,
            bot=bot,
            primary_bot_id=bot.id,
            messages=[],
            user_message=user_message,
            ctx=_empty_ctx(),
            req=ChatRequest(message=user_message, bot_id=bot.id),
            user=None,
            audio_data=None,
            audio_format=None,
            att_payload=None,
        )


class _FakeRuntime:
    """In-test stand-in for ClaudeCodeRuntime."""

    def __init__(self, *, result: TurnResult | None = None, raises: Exception | None = None):
        self._result = result or TurnResult(
            session_id="sess_xyz",
            final_text="all done",
            cost_usd=0.0042,
            usage={"input_tokens": 10, "output_tokens": 20},
        )
        self._raises = raises
        self.captured: dict | None = None

    @property
    def name(self) -> str:
        return "claude-code"

    async def start_turn(self, *, workdir, prompt, session_id, emit):
        self.captured = {
            "workdir": workdir,
            "prompt": prompt,
            "session_id": session_id,
            "emit": emit,
        }
        if self._raises is not None:
            raise self._raises
        # Simulate the bridge emitting one assistant text chunk.
        emit.token(self._result.final_text)
        return self._result

    def auth_status(self):  # pragma: no cover - not exercised here
        from app.services.agent_harnesses.base import AuthStatus
        return AuthStatus(ok=True, detail="test")


class TestHarnessDispatch:
    async def test_when_harness_succeeds_then_assistant_message_persisted_with_harness_metadata(
        self, db_session, harness_setup,
    ):
        handle = harness_setup
        runtime = _FakeRuntime()

        await _drive_harness_turn(handle, fake_runtime=runtime)

        # Driver was called with expected kwargs.
        assert runtime.captured is not None
        assert runtime.captured["workdir"] == "/tmp/test-workspace"
        assert runtime.captured["prompt"] == "list files"
        assert runtime.captured["session_id"] is None  # first turn

        # Assistant row persisted with harness metadata.
        rows = (await db_session.execute(
            select(MessageRow).where(
                MessageRow.session_id == handle.session_id,
                MessageRow.role == "assistant",
            )
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].content == "all done"
        meta = rows[0].metadata_
        assert "harness" in meta
        assert meta["harness"]["runtime"] == "claude-code"
        assert meta["harness"]["session_id"] == "sess_xyz"
        assert meta["harness"]["cost_usd"] == 0.0042

    async def test_session_state_written_back_for_resume(
        self, db_session, harness_setup,
    ):
        handle = harness_setup
        runtime = _FakeRuntime()

        await _drive_harness_turn(handle, fake_runtime=runtime)

        bot_row = await db_session.get(BotRow, HARNESS_BOT_CFG.id)
        await db_session.refresh(bot_row)
        assert bot_row.harness_session_state is not None
        assert bot_row.harness_session_state["session_id"] == "sess_xyz"
        assert bot_row.harness_session_state["cost_total"] == 0.0042

    async def test_resume_passes_prior_session_id_to_driver(
        self, db_session, harness_setup,
    ):
        handle = harness_setup
        # Seed a prior session_id on the bot.
        bot_row = await db_session.get(BotRow, HARNESS_BOT_CFG.id)
        bot_row.harness_session_state = {"session_id": "prior_session", "cost_total": 0.01}
        await db_session.commit()

        bot_cfg_with_state = BotConfig(
            id=HARNESS_BOT_CFG.id,
            name=HARNESS_BOT_CFG.name,
            model="",
            system_prompt="",
            memory=MemoryConfig(enabled=False),
            harness_runtime="claude-code",
            harness_workdir="/tmp/test-workspace",
            harness_session_state={"session_id": "prior_session", "cost_total": 0.01},
        )

        runtime = _FakeRuntime()
        await _drive_harness_turn(handle, fake_runtime=runtime, bot_cfg=bot_cfg_with_state)

        assert runtime.captured["session_id"] == "prior_session"

    async def test_when_harness_raises_then_failure_message_persisted_and_turn_ended_has_error(
        self, db_session, harness_setup,
    ):
        handle = harness_setup
        runtime = _FakeRuntime(raises=RuntimeError("oauth missing"))

        await _drive_harness_turn(handle, fake_runtime=runtime)

        rows = (await db_session.execute(
            select(MessageRow).where(
                MessageRow.session_id == handle.session_id,
                MessageRow.role == "assistant",
            )
        )).scalars().all()
        assert len(rows) == 1
        assert "Turn failed" in rows[0].content or "oauth missing" in rows[0].content

        ended = [
            ev for ev in _replay_buffer.get(handle.channel_id, [])
            if ev.kind is ChannelEventKind.TURN_ENDED
        ]
        assert len(ended) == 1
        assert ended[0].payload.error is not None
        assert "oauth missing" in ended[0].payload.error

    async def test_turn_started_published_before_harness_runs(
        self, db_session, harness_setup,
    ):
        handle = harness_setup
        runtime = _FakeRuntime()

        await _drive_harness_turn(handle, fake_runtime=runtime)

        kinds = [ev.kind for ev in _replay_buffer.get(handle.channel_id, [])]
        assert ChannelEventKind.TURN_STARTED in kinds
        assert ChannelEventKind.TURN_ENDED in kinds
        # TURN_STARTED must come before TURN_ENDED.
        assert kinds.index(ChannelEventKind.TURN_STARTED) < kinds.index(ChannelEventKind.TURN_ENDED)

    async def test_lock_released_after_harness_turn(
        self, db_session, harness_setup,
    ):
        handle = harness_setup
        runtime = _FakeRuntime()
        assert session_locks.is_active(handle.session_id)

        await _drive_harness_turn(handle, fake_runtime=runtime)

        assert not session_locks.is_active(handle.session_id)
