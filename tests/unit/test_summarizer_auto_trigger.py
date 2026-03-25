"""Tests for auto-summarize trigger in app.agent.loop.run_stream().

Tests the idle-detection logic that auto-injects a summary system message
when a channel has been idle longer than the configured threshold.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
from app.agent.context_assembly import AssemblyResult


def _make_bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test", name="Test", model="gpt-4",
        system_prompt="You are a test bot.",
        memory=MemoryConfig(), knowledge=KnowledgeConfig(),
        compression_config={},
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _patch_stack():
    """Return patch context managers for run_stream dependencies."""
    async def fake_assemble(*a, **kw):
        return
        yield  # async generator that yields nothing

    return {
        "assemble": patch("app.agent.loop.assemble_context", fake_assemble),
        "tool_schemas": patch("app.agent.loop.get_local_tool_schemas", return_value=[]),
        "trace": patch("app.agent.loop._record_trace_event", new_callable=AsyncMock),
        # compress_context is imported inside run_stream from app.services.compression
        "compress": patch("app.services.compression.compress_context", new_callable=AsyncMock, return_value=None),
        # run_agent_tool_loop needs to be patched
        "loop": patch("app.agent.loop.run_agent_tool_loop"),
    }


def _fake_channel(enabled=True, threshold_minutes=30, message_count=50):
    ch = MagicMock()
    ch.summarizer_enabled = enabled
    ch.summarizer_threshold_minutes = threshold_minutes
    ch.summarizer_message_count = message_count
    return ch


# ---------------------------------------------------------------------------
# Auto-summarize trigger
# ---------------------------------------------------------------------------

class TestAutoSummarizeTrigger:

    @pytest.mark.asyncio
    async def test_auto_summarize_fires_when_idle(self):
        """When channel is idle > threshold, an auto_summarize trace event is emitted."""
        from app.agent.loop import run_stream

        bot = _make_bot()
        channel_id = uuid.uuid4()
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello again"},
        ]

        last_ts = datetime.now(timezone.utc) - timedelta(minutes=60)
        ch = _fake_channel(enabled=True, threshold_minutes=30)

        async def fake_tool_loop(msgs, *a, **kw):
            yield {"type": "response", "content": "ok"}

        p = _patch_stack()
        with (
            p["assemble"], p["tool_schemas"], p["trace"], p["compress"],
            p["loop"] as mock_loop,
            patch("app.services.summarizer.get_last_user_message_time", new_callable=AsyncMock, return_value=last_ts),
            patch("app.services.summarizer.summarize_messages", new_callable=AsyncMock, return_value="Here is the summary."),
            patch("app.db.engine.async_session") as mock_session_factory,
        ):
            # Mock DB session for channel lookup
            mock_db = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=False)
            fake_result = MagicMock()
            fake_result.scalar_one_or_none.return_value = ch
            mock_db.execute = AsyncMock(return_value=fake_result)
            mock_session_factory.return_value = mock_db

            mock_loop.side_effect = fake_tool_loop

            events = []
            async for event in run_stream(
                messages, bot, "Hello again",
                session_id=uuid.uuid4(), channel_id=channel_id,
            ):
                events.append(event)

        event_types = [(e.get("type"), e.get("event_type")) for e in events]
        assert ("trace", "auto_summarize") in event_types

        # Summary should be injected as a system message
        sys_msgs = [m for m in messages if m.get("role") == "system"]
        auto_summary_msgs = [m for m in sys_msgs if "Auto-summary" in m.get("content", "")]
        assert len(auto_summary_msgs) == 1
        assert "Here is the summary" in auto_summary_msgs[0]["content"]

    @pytest.mark.asyncio
    async def test_auto_summarize_skipped_when_not_idle(self):
        """When channel is idle < threshold, no auto_summarize event is emitted."""
        from app.agent.loop import run_stream

        bot = _make_bot()
        channel_id = uuid.uuid4()
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Quick follow-up"},
        ]

        last_ts = datetime.now(timezone.utc) - timedelta(minutes=5)
        ch = _fake_channel(enabled=True, threshold_minutes=30)

        async def fake_tool_loop(msgs, *a, **kw):
            yield {"type": "response", "content": "ok"}

        p = _patch_stack()
        with (
            p["assemble"], p["tool_schemas"], p["trace"], p["compress"],
            p["loop"] as mock_loop,
            patch("app.services.summarizer.get_last_user_message_time", new_callable=AsyncMock, return_value=last_ts),
            patch("app.db.engine.async_session") as mock_session_factory,
        ):
            mock_db = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=False)
            fake_result = MagicMock()
            fake_result.scalar_one_or_none.return_value = ch
            mock_db.execute = AsyncMock(return_value=fake_result)
            mock_session_factory.return_value = mock_db

            mock_loop.side_effect = fake_tool_loop

            events = []
            async for event in run_stream(
                messages, bot, "Quick follow-up",
                session_id=uuid.uuid4(), channel_id=channel_id,
            ):
                events.append(event)

        event_types = [(e.get("type"), e.get("event_type")) for e in events]
        assert ("trace", "auto_summarize") not in event_types

    @pytest.mark.asyncio
    async def test_auto_summarize_skipped_when_disabled(self):
        """When summarizer_enabled is False, no auto_summarize runs."""
        from app.agent.loop import run_stream

        bot = _make_bot()
        channel_id = uuid.uuid4()
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
        ]

        ch = _fake_channel(enabled=False)

        async def fake_tool_loop(msgs, *a, **kw):
            yield {"type": "response", "content": "ok"}

        p = _patch_stack()
        with (
            p["assemble"], p["tool_schemas"], p["trace"], p["compress"],
            p["loop"] as mock_loop,
            patch("app.db.engine.async_session") as mock_session_factory,
        ):
            mock_db = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=False)
            fake_result = MagicMock()
            fake_result.scalar_one_or_none.return_value = ch
            mock_db.execute = AsyncMock(return_value=fake_result)
            mock_session_factory.return_value = mock_db

            mock_loop.side_effect = fake_tool_loop

            events = []
            async for event in run_stream(
                messages, bot, "Hello",
                session_id=uuid.uuid4(), channel_id=channel_id,
            ):
                events.append(event)

        event_types = [(e.get("type"), e.get("event_type")) for e in events]
        assert ("trace", "auto_summarize") not in event_types

    @pytest.mark.asyncio
    async def test_auto_summarize_skipped_no_channel_id(self):
        """When no channel_id is provided, auto-summarize is skipped entirely."""
        from app.agent.loop import run_stream

        bot = _make_bot()
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
        ]

        async def fake_tool_loop(msgs, *a, **kw):
            yield {"type": "response", "content": "ok"}

        p = _patch_stack()
        with (
            p["assemble"], p["tool_schemas"], p["trace"], p["compress"],
            p["loop"] as mock_loop,
        ):
            mock_loop.side_effect = fake_tool_loop

            events = []
            async for event in run_stream(
                messages, bot, "Hello",
                session_id=uuid.uuid4(),
                # no channel_id
            ):
                events.append(event)

        event_types = [(e.get("type"), e.get("event_type")) for e in events]
        assert ("trace", "auto_summarize") not in event_types

    @pytest.mark.asyncio
    async def test_auto_summarize_error_doesnt_break_loop(self):
        """If summarizer throws, the agent loop still runs normally."""
        from app.agent.loop import run_stream

        bot = _make_bot()
        channel_id = uuid.uuid4()
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Hello"},
        ]

        async def fake_tool_loop(msgs, *a, **kw):
            yield {"type": "response", "content": "ok"}

        p = _patch_stack()
        with (
            p["assemble"], p["tool_schemas"], p["trace"], p["compress"],
            p["loop"] as mock_loop,
            patch("app.db.engine.async_session", side_effect=RuntimeError("DB down")),
        ):
            mock_loop.side_effect = fake_tool_loop

            events = []
            async for event in run_stream(
                messages, bot, "Hello",
                session_id=uuid.uuid4(), channel_id=channel_id,
            ):
                events.append(event)

        # Should still get a response despite the error
        response_events = [e for e in events if e.get("type") == "response"]
        assert len(response_events) == 1
