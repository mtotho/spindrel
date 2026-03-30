"""Integration tests for app.services.compaction — memory phase, summary generation, compaction stream."""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
from app.db.models import Message, Session
from tests.integration.conftest import engine, db_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test-bot", name="Test Bot", model="test/model",
        system_prompt="System prompt.",
        context_compaction=True,
        compaction_interval=3,
        compaction_keep_turns=1,
        memory=MemoryConfig(enabled=False),
        knowledge=KnowledgeConfig(enabled=False),
        history_mode="summary",
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _mock_llm_response(content):
    resp = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = []
    choice.message.model_dump.return_value = {"role": "assistant", "content": content}
    choice.finish_reason = "stop"
    resp.choices = [choice]
    resp.usage = MagicMock(prompt_tokens=50, completion_tokens=30, total_tokens=80)
    return resp


# ---------------------------------------------------------------------------
# _messages_for_summary
# ---------------------------------------------------------------------------

class TestMessagesForSummary:
    def test_excludes_passive_from_active(self):
        from app.services.compaction import _messages_for_summary
        msgs = [
            {"role": "user", "content": "active msg"},
            {"role": "user", "content": "passive msg", "_metadata": {"passive": True, "sender_id": "U1"}},
            {"role": "assistant", "content": "response"},
        ]
        result = _messages_for_summary(msgs)
        # Passive should become a system "Channel context" block
        sys_msgs = [m for m in result if m["role"] == "system"]
        assert len(sys_msgs) == 1
        assert "Channel context" in sys_msgs[0]["content"]
        # Active messages preserved
        active = [m for m in result if m["role"] != "system"]
        assert len(active) == 2

    def test_no_passive_no_system(self):
        from app.services.compaction import _messages_for_summary
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        result = _messages_for_summary(msgs)
        assert not any(m["role"] == "system" for m in result)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _generate_summary
# ---------------------------------------------------------------------------

class TestGenerateSummary:
    @pytest.mark.asyncio
    async def test_returns_title_and_summary(self):
        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "Chat about weather", "summary": "User asked about weather."}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            from app.services.compaction import _generate_summary
            title, summary, _usage = await _generate_summary(
                [{"role": "user", "content": "what's the weather?"}],
                "test/model", None,
            )

        assert title == "Chat about weather"
        assert "weather" in summary.lower()

    @pytest.mark.asyncio
    async def test_handles_markdown_fenced_json(self):
        mock_client = AsyncMock()
        raw = '```json\n{"title": "T", "summary": "S"}\n```'
        resp = _mock_llm_response(raw)
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            from app.services.compaction import _generate_summary
            title, summary, _usage = await _generate_summary([], "test/model", None)

        assert title == "T"
        assert summary == "S"

    @pytest.mark.asyncio
    async def test_fallback_on_non_json(self):
        mock_client = AsyncMock()
        resp = _mock_llm_response("Just a plain text summary")
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            from app.services.compaction import _generate_summary
            title, summary, _usage = await _generate_summary([], "test/model", None)

        assert title == "Conversation"
        assert summary == "Just a plain text summary"

    @pytest.mark.asyncio
    async def test_includes_existing_summary_in_prompt(self):
        mock_client = AsyncMock()
        resp = _mock_llm_response('{"title": "T", "summary": "S"}')
        mock_client.chat.completions.create = AsyncMock(return_value=resp)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            from app.services.compaction import _generate_summary
            await _generate_summary([], "test/model", "Previous summary text")

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        # Should have system + existing summary + conversation
        assert any("Previous summary" in m.get("content", "") for m in messages)


# ---------------------------------------------------------------------------
# run_compaction_stream
# ---------------------------------------------------------------------------

class TestRunCompactionStream:
    @pytest.mark.asyncio
    async def test_skips_when_compaction_disabled(self, engine):
        bot = _bot(context_compaction=False)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with factory() as db:
            sid = uuid.uuid4()
            session = Session(id=sid, client_id="c", bot_id=bot.id)
            db.add(session)
            await db.commit()

        with patch("app.services.compaction.async_session", factory):
            from app.services.compaction import run_compaction_stream
            events = []
            async for event in run_compaction_stream(sid, bot, []):
                events.append(event)

        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_skips_when_not_enough_turns(self, engine):
        bot = _bot(compaction_interval=10)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with factory() as db:
            sid = uuid.uuid4()
            session = Session(id=sid, client_id="c", bot_id=bot.id)
            db.add(session)
            # Add only 2 user messages (below interval of 10)
            for i in range(2):
                db.add(Message(session_id=sid, role="user", content=f"msg {i}"))
            await db.commit()

        with patch("app.services.compaction.async_session", factory):
            from app.services.compaction import run_compaction_stream
            events = []
            async for event in run_compaction_stream(sid, bot, []):
                events.append(event)

        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_runs_when_enough_turns(self, engine):
        """When user message count >= interval, compaction runs and yields events."""
        bot = _bot(compaction_interval=3, compaction_keep_turns=1)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with factory() as db:
            sid = uuid.uuid4()
            session = Session(id=sid, client_id="c", bot_id=bot.id)
            db.add(session)
            # Add enough user messages
            for i in range(4):
                db.add(Message(session_id=sid, role="user", content=f"msg {i}"))
            for i in range(4):
                db.add(Message(session_id=sid, role="assistant", content=f"reply {i}"))
            await db.commit()

        summary_resp = _mock_llm_response('{"title": "Test chat", "summary": "A test conversation."}')
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=summary_resp)

        messages = [
            {"role": "user", "content": f"msg {i}"} for i in range(4)
        ] + [
            {"role": "assistant", "content": f"reply {i}"} for i in range(4)
        ]

        with (
            patch("app.services.compaction.async_session", factory),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.services.compaction._record_trace_event", new_callable=AsyncMock),
        ):
            from app.services.compaction import run_compaction_stream
            events = []
            async for event in run_compaction_stream(sid, bot, messages):
                events.append(event)

        types = [e.get("type") for e in events]
        assert "compaction_done" in types
        done_event = next(e for e in events if e["type"] == "compaction_done")
        assert done_event["title"] == "Test chat"

        # Verify session updated with summary
        async with factory() as db:
            session = await db.get(Session, sid)
            assert session.summary == "A test conversation."
            assert session.title == "Test chat"
