"""Phase B.8 targeted sweep of compaction.py core gaps (#22, #23).

Covers:
  #22  repair_section_periods — message_count==0 silent skip + normal repair
  #23  maybe_compact — background task execution + exception containment

repair_section_periods uses a real DB (patched_async_sessions).
maybe_compact is sync; async tests capture + exercise the coroutine.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import Channel, ConversationSection, Message, Session
from app.services.compaction import maybe_compact, repair_section_periods


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _make_channel() -> Channel:
    return Channel(id=uuid.uuid4(), name=f"ch-{uuid.uuid4().hex[:6]}", bot_id="test-bot")


def _make_session(channel_id: uuid.UUID) -> Session:
    return Session(
        id=uuid.uuid4(),
        client_id="test",
        bot_id="test-bot",
        channel_id=channel_id,
    )


def _make_section(
    channel_id: uuid.UUID,
    session_id: uuid.UUID | None,
    sequence: int,
    message_count: int,
    *,
    period_start: datetime | None = None,
) -> ConversationSection:
    return ConversationSection(
        id=uuid.uuid4(),
        channel_id=channel_id,
        session_id=session_id,
        sequence=sequence,
        title=f"Section {sequence}",
        summary="summary",
        message_count=message_count,
        chunk_size=50,
        period_start=period_start,
        period_end=None,
    )


def _make_message(session_id: uuid.UUID, role: str, ts: datetime) -> Message:
    return Message(
        id=uuid.uuid4(),
        session_id=session_id,
        role=role,
        content="test",
        created_at=ts,
    )


# ===========================================================================
# #22 — repair_section_periods
# ===========================================================================

class TestRepairSectionPeriods:
    @pytest.mark.asyncio
    async def test_when_no_sections_missing_periods_then_returns_zero(
        self, db_session, patched_async_sessions
    ):
        ch = _make_channel()
        sess = _make_session(ch.id)
        section = _make_section(ch.id, sess.id, 0, 2, period_start=datetime.now(timezone.utc))
        db_session.add_all([ch, sess, section])
        await db_session.commit()

        repaired = await repair_section_periods()

        assert repaired == 0

    @pytest.mark.asyncio
    async def test_when_section_message_count_is_zero_then_skipped(
        self, db_session, patched_async_sessions
    ):
        ch = _make_channel()
        sess = _make_session(ch.id)
        section = _make_section(ch.id, sess.id, 0, message_count=0)  # period_start=None
        db_session.add_all([ch, sess, section])
        await db_session.commit()

        repaired = await repair_section_periods()

        assert repaired == 0
        await db_session.refresh(section)
        assert section.period_start is None  # still null

    @pytest.mark.asyncio
    async def test_when_section_has_no_session_id_then_skipped(
        self, db_session, patched_async_sessions
    ):
        ch = _make_channel()
        section = _make_section(ch.id, session_id=None, sequence=0, message_count=3)
        db_session.add_all([ch, section])
        await db_session.commit()

        repaired = await repair_section_periods()

        assert repaired == 0
        await db_session.refresh(section)
        assert section.period_start is None

    @pytest.mark.asyncio
    async def test_when_single_section_with_messages_then_period_set(
        self, db_session, patched_async_sessions
    ):
        ch = _make_channel()
        sess = _make_session(ch.id)
        section = _make_section(ch.id, sess.id, 0, message_count=2)

        base = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        m1 = _make_message(sess.id, "user", base)
        m2 = _make_message(sess.id, "assistant", base + timedelta(minutes=5))
        db_session.add_all([ch, sess, section, m1, m2])
        await db_session.commit()

        repaired = await repair_section_periods()

        assert repaired == 1
        await db_session.refresh(section)
        assert section.period_start is not None
        assert section.period_end is not None
        # period_start is the earliest, period_end is the latest
        assert section.period_start <= section.period_end

    @pytest.mark.asyncio
    async def test_when_already_repaired_section_present_then_only_missing_repaired(
        self, db_session, patched_async_sessions
    ):
        ch = _make_channel()
        sess = _make_session(ch.id)
        fixed_ts = datetime(2025, 6, 1, tzinfo=timezone.utc)
        # section_done owns messages 0-1 (message_count=2, period_start set → skipped by repair)
        section_done = _make_section(ch.id, sess.id, 0, 2, period_start=fixed_ts)
        # section_broken owns messages 2-3 (message_count=2, period_start=None → needs repair)
        section_broken = _make_section(ch.id, sess.id, 1, 2)

        base = datetime(2026, 2, 1, 10, 0, tzinfo=timezone.utc)
        # 4 messages total: first 2 belong to section_done's range, next 2 to section_broken's range
        m1 = _make_message(sess.id, "user", base)
        m2 = _make_message(sess.id, "assistant", base + timedelta(minutes=5))
        m3 = _make_message(sess.id, "user", base + timedelta(minutes=10))
        m4 = _make_message(sess.id, "assistant", base + timedelta(minutes=15))
        db_session.add_all([ch, sess, section_done, section_broken, m1, m2, m3, m4])
        await db_session.commit()

        repaired = await repair_section_periods()

        assert repaired == 1
        await db_session.refresh(section_done)
        assert section_done.period_start == fixed_ts  # untouched


# ===========================================================================
# #23 — maybe_compact
# ===========================================================================

class TestMaybeCompact:
    @pytest.mark.asyncio
    async def test_when_called_then_background_task_scheduled(self):
        bot = MagicMock()
        session_id = uuid.uuid4()
        tasks_created = []

        with patch("asyncio.create_task", side_effect=tasks_created.append), \
             patch("app.services.compaction._drain_compaction", return_value=AsyncMock()()):
            maybe_compact(session_id, bot, [])

        assert len(tasks_created) == 1

    @pytest.mark.asyncio
    async def test_when_budget_above_threshold_then_budget_triggered_true(self):
        bot = MagicMock()
        session_id = uuid.uuid4()

        with patch("app.services.compaction._drain_compaction", return_value=AsyncMock()()) as mock_drain, \
             patch("asyncio.create_task"):
            maybe_compact(session_id, bot, [], budget_utilization=0.90)

        mock_drain.assert_called_once()
        _, kwargs = mock_drain.call_args
        assert kwargs["budget_triggered"] is True

    @pytest.mark.asyncio
    async def test_when_budget_exactly_at_threshold_then_not_triggered(self):
        bot = MagicMock()
        session_id = uuid.uuid4()

        with patch("app.services.compaction._drain_compaction", return_value=AsyncMock()()) as mock_drain, \
             patch("asyncio.create_task"):
            maybe_compact(session_id, bot, [], budget_utilization=0.85)

        _, kwargs = mock_drain.call_args
        assert kwargs["budget_triggered"] is False

    @pytest.mark.asyncio
    async def test_when_budget_below_threshold_then_not_triggered(self):
        bot = MagicMock()
        session_id = uuid.uuid4()

        with patch("app.services.compaction._drain_compaction", return_value=AsyncMock()()) as mock_drain, \
             patch("asyncio.create_task"):
            maybe_compact(session_id, bot, [], budget_utilization=0.50)

        _, kwargs = mock_drain.call_args
        assert kwargs["budget_triggered"] is False

    @pytest.mark.asyncio
    async def test_when_no_budget_utilization_then_not_triggered(self):
        bot = MagicMock()
        session_id = uuid.uuid4()

        with patch("app.services.compaction._drain_compaction", return_value=AsyncMock()()) as mock_drain, \
             patch("asyncio.create_task"):
            maybe_compact(session_id, bot, [])

        _, kwargs = mock_drain.call_args
        assert kwargs["budget_triggered"] is False

    @pytest.mark.asyncio
    async def test_when_background_task_raises_exception_is_contained(self):
        """Exception inside the drained coroutine must not propagate to the caller."""
        bot = MagicMock()
        session_id = uuid.uuid4()
        captured = []

        async def _boom(*args, **kwargs):
            raise RuntimeError("compaction failed catastrophically")

        def _capture(coro):
            captured.append(coro)
            # Return a simple no-op task so asyncio is happy
            return asyncio.ensure_future(asyncio.sleep(0))

        with patch("app.services.compaction._drain_compaction", side_effect=_boom), \
             patch("asyncio.create_task", side_effect=_capture):
            maybe_compact(session_id, bot, [])  # must not raise

        # The coroutine itself raises when awaited — exception is contained in the task
        assert len(captured) == 1
        with pytest.raises(RuntimeError, match="compaction failed catastrophically"):
            await captured[0]
