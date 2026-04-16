"""Tests for compaction logging, period date fix, and usage capture."""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import BotConfig, MemoryConfig


def _make_bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test", name="Test", model="gpt-4",
        system_prompt="You are a test bot.",
        memory=MemoryConfig(),
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _mock_llm_response(content: str, prompt_tokens=100, completion_tokens=50):
    """Build a mock ChatCompletion response with usage."""
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    return resp


# ---------------------------------------------------------------------------
# _generate_section returns 5-tuple with usage_info
# ---------------------------------------------------------------------------

class TestGenerateSectionUsage:
    @pytest.mark.asyncio
    async def test_normal_tier_returns_usage(self):
        """_generate_section returns (title, summary, transcript, tags, usage_info)."""
        from app.services.compaction import _generate_section

        section_json = json.dumps({
            "title": "Test Section",
            "summary": "A test summary.",
            "tags": ["test", "compaction"],
        })
        mock_response = _mock_llm_response(section_json, prompt_tokens=200, completion_tokens=80)

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        conversation = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            with patch("app.services.compaction.async_session") as mock_session_ctx:
                mock_db = AsyncMock()
                mock_db.execute = AsyncMock(return_value=MagicMock(
                    scalar=MagicMock(return_value=0),
                ))
                mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
                mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await _generate_section(conversation, "gpt-4")

        assert len(result) == 5
        title, summary, transcript, tags, usage_info = result
        assert title == "Test Section"
        assert summary == "A test summary."
        assert tags == ["test", "compaction"]
        assert usage_info["tier"] == "normal"
        assert usage_info["prompt_tokens"] == 200
        assert usage_info["completion_tokens"] == 80

    @pytest.mark.asyncio
    async def test_deterministic_tier_returns_no_tokens(self):
        """When LLM fails twice, deterministic tier returns None tokens."""
        from app.services.compaction import _generate_section

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("LLM fail"))

        conversation = [
            {"role": "user", "content": "Hello world"},
            {"role": "assistant", "content": "Hi"},
        ]

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            with patch("app.services.compaction.async_session") as mock_session_ctx:
                mock_db = AsyncMock()
                mock_db.execute = AsyncMock(return_value=MagicMock(
                    scalar=MagicMock(return_value=0),
                ))
                mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
                mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

                result = await _generate_section(conversation, "gpt-4")

        title, summary, transcript, tags, usage_info = result
        assert usage_info["tier"] == "deterministic"
        assert usage_info["prompt_tokens"] is None
        assert usage_info["completion_tokens"] is None
        assert "Hello world" in title


# ---------------------------------------------------------------------------
# _generate_summary returns 3-tuple with usage_info
# ---------------------------------------------------------------------------

class TestGenerateSummaryUsage:
    @pytest.mark.asyncio
    async def test_returns_usage_info(self):
        """_generate_summary returns (title, summary, usage_info)."""
        from app.services.compaction import _generate_summary

        summary_json = json.dumps({
            "title": "Summary Title",
            "summary": "A brief summary.",
        })
        mock_response = _mock_llm_response(summary_json, prompt_tokens=150, completion_tokens=40)

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        conversation = [
            {"role": "user", "content": "What is the weather?"},
            {"role": "assistant", "content": "It's sunny."},
        ]

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            result = await _generate_summary(conversation, "gpt-4", None)

        assert len(result) == 3
        title, summary, usage_info = result
        assert title == "Summary Title"
        assert summary == "A brief summary."
        assert usage_info["tier"] == "normal"
        assert usage_info["prompt_tokens"] == 150
        assert usage_info["completion_tokens"] == 40

    @pytest.mark.asyncio
    async def test_non_json_response_still_returns_usage(self):
        """Non-JSON response still includes usage_info."""
        from app.services.compaction import _generate_summary

        mock_response = _mock_llm_response("Just plain text", prompt_tokens=50, completion_tokens=10)

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        conversation = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            title, summary, usage_info = await _generate_summary(conversation, "gpt-4", None)

        assert title == "Conversation"  # fallback title
        assert usage_info["prompt_tokens"] == 50
        assert usage_info["completion_tokens"] == 10


# ---------------------------------------------------------------------------
# _record_compaction_log
# ---------------------------------------------------------------------------

class TestRecordCompactionLog:
    @pytest.mark.asyncio
    async def test_records_log_entry(self):
        """_record_compaction_log creates a CompactionLog row."""
        from app.services.compaction import _record_compaction_log

        added_objects = []

        mock_db = AsyncMock()
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        mock_db.commit = AsyncMock()

        with patch("app.services.compaction.async_session") as mock_session_ctx:
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            corr_id = uuid.uuid4()
            await _record_compaction_log(
                channel_id=uuid.uuid4(),
                session_id=uuid.uuid4(),
                bot_id="test-bot",
                model="gpt-4",
                history_mode="file",
                tier="normal",
                forced=False,
                memory_flush=True,
                messages_archived=15,
                prompt_tokens=200,
                completion_tokens=80,
                duration_ms=3500,
                section_id=uuid.uuid4(),
                correlation_id=corr_id,
                flush_result="Updated MEMORY.md with session notes.",
            )

        assert len(added_objects) == 1
        log = added_objects[0]
        assert log.bot_id == "test-bot"
        assert log.model == "gpt-4"
        assert log.history_mode == "file"
        assert log.tier == "normal"
        assert log.forced is False
        assert log.memory_flush is True
        assert log.messages_archived == 15
        assert log.prompt_tokens == 200
        assert log.completion_tokens == 80
        assert log.duration_ms == 3500
        assert log.correlation_id == corr_id
        assert log.flush_result == "Updated MEMORY.md with session notes."
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_swallows_exceptions(self):
        """_record_compaction_log should not raise on DB errors."""
        from app.services.compaction import _record_compaction_log

        with patch("app.services.compaction.async_session") as mock_session_ctx:
            mock_session_ctx.return_value.__aenter__ = AsyncMock(
                side_effect=Exception("DB down")
            )
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            # Should not raise
            await _record_compaction_log(
                channel_id=None,
                session_id=None,
                bot_id="test",
                model="gpt-4",
                history_mode="summary",
                tier="normal",
            )

    @pytest.mark.asyncio
    async def test_optional_fields_default_none(self):
        """Optional fields should accept None values."""
        from app.services.compaction import _record_compaction_log

        added_objects = []
        mock_db = AsyncMock()
        mock_db.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
        mock_db.commit = AsyncMock()

        with patch("app.services.compaction.async_session") as mock_session_ctx:
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            await _record_compaction_log(
                channel_id=None,
                session_id=None,
                bot_id="test",
                model="gpt-4",
                history_mode="summary",
                tier="aggressive",
            )

        log = added_objects[0]
        assert log.channel_id is None
        assert log.session_id is None
        assert log.messages_archived is None
        assert log.prompt_tokens is None
        assert log.completion_tokens is None
        assert log.duration_ms is None
        assert log.section_id is None
        assert log.error is None
        assert log.correlation_id is None
        assert log.flush_result is None
        assert log.tier == "aggressive"


# ---------------------------------------------------------------------------
# CompactionLog ORM model
# ---------------------------------------------------------------------------

class TestCompactionLogModel:
    def test_model_fields(self):
        """CompactionLog has all required fields."""
        from app.db.models import CompactionLog

        log = CompactionLog(
            bot_id="test",
            model="gpt-4",
            history_mode="file",
            tier="normal",
        )
        assert log.bot_id == "test"
        assert log.prompt_tokens is None
        assert log.completion_tokens is None
        assert log.duration_ms is None
        assert log.error is None
        assert log.section_id is None
        assert log.correlation_id is None
        assert log.flush_result is None

    def test_table_name(self):
        from app.db.models import CompactionLog
        assert CompactionLog.__tablename__ == "compaction_logs"


# ---------------------------------------------------------------------------
# Period date bug fix — structural verification
# ---------------------------------------------------------------------------

class TestPeriodDateFix:
    def test_stream_path_captures_prev_watermark(self):
        """run_compaction_stream captures prev_watermark_id and uses it as lower bound."""
        import inspect
        from app.services.compaction import run_compaction_stream

        source = inspect.getsource(run_compaction_stream)
        assert "prev_watermark_id = session.summary_message_id" in source
        assert "Message.created_at > prev_wm_msg.created_at" in source

    def test_forced_path_captures_prev_watermark(self):
        """run_compaction_forced captures prev_watermark_id and uses it as lower bound."""
        import inspect
        from app.services.compaction import run_compaction_forced

        source = inspect.getsource(run_compaction_forced)
        assert "prev_watermark_id = session.summary_message_id" in source
        assert "Message.created_at > prev_wm_msg.created_at" in source
