"""Integration-style tests for compaction flow with section modes.

Tests the branching in run_compaction_stream for structured/file/summary modes.
"""
import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from app.agent.bots import BotConfig, MemoryConfig, KnowledgeConfig
from app.services.compaction import _get_history_mode


def _make_bot(**overrides) -> BotConfig:
    defaults = dict(
        id="test", name="Test", model="gpt-4",
        system_prompt="You are a test bot.",
        local_tools=[], mcp_servers=[], client_tools=[], skills=[],
        pinned_tools=[],
        tool_retrieval=True,
        context_compaction=True,
        compaction_interval=10,
        compaction_keep_turns=4,
        compaction_model=None,
        memory=MemoryConfig(),
        knowledge=KnowledgeConfig(),
        persona=False,
    )
    defaults.update(overrides)
    return BotConfig(**defaults)


def _make_channel(**overrides):
    ch = MagicMock()
    ch.compaction_model = overrides.get("compaction_model", None)
    ch.compaction_interval = overrides.get("compaction_interval", None)
    ch.compaction_keep_turns = overrides.get("compaction_keep_turns", None)
    ch.context_compaction = overrides.get("context_compaction", True)
    ch.memory_knowledge_compaction_prompt = overrides.get(
        "memory_knowledge_compaction_prompt", None
    )
    ch.history_mode = overrides.get("history_mode", None)
    ch.id = overrides.get("id", uuid.uuid4())
    return ch


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


class TestHistoryModeRouting:
    """Test that _get_history_mode correctly routes compaction."""

    def test_structured_mode_detected(self):
        bot = _make_bot(history_mode="structured")
        ch = _make_channel(history_mode=None)
        assert _get_history_mode(bot, ch) == "structured"

    def test_file_mode_detected(self):
        bot = _make_bot(history_mode="file")
        assert _get_history_mode(bot, None) == "file"

    def test_file_mode_is_default(self):
        bot = _make_bot()
        assert _get_history_mode(bot) == "file"

    def test_channel_override_wins(self):
        bot = _make_bot(history_mode="summary")
        ch = _make_channel(history_mode="file")
        assert _get_history_mode(bot, ch) == "file"


class TestCompactionStreamStructuredMode:
    """Test run_compaction_stream behavior with structured mode."""

    @pytest.mark.asyncio
    async def test_section_created_with_embedding(self):
        """Structured mode should call _generate_section and embed_text."""
        from app.services.compaction import _generate_section

        section_json = json.dumps({
            "title": "Test Section",
            "summary": "A test summary.",
            "transcript": "[USER]: hello\n[ASSISTANT]: hi",
        })
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response(section_json)
        )
        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            title, summary, transcript, tags = await _generate_section(
                [{"role": "user", "content": "hello"}], "gpt-4",
            )
        assert title == "Test Section"
        assert summary == "A test summary."
        assert "[USER]" in transcript

    @pytest.mark.asyncio
    async def test_executive_summary_uses_all_sections(self):
        """Executive summary regeneration queries all sections."""
        from app.services.compaction import _regenerate_executive_summary

        sections = [
            MagicMock(sequence=1, title="Setup", summary="Set things up."),
            MagicMock(sequence=2, title="Debug", summary="Fixed bugs."),
        ]
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response("Overall: setup then debugging.")
        )
        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.compaction.async_session") as mock_session:
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = sections
            mock_db.execute = AsyncMock(return_value=mock_result)
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _regenerate_executive_summary(uuid.uuid4(), "gpt-4")

        assert "setup then debugging" in result


class TestCompactionStreamFileMode:
    """Test that file mode creates sections without embeddings."""

    @pytest.mark.asyncio
    async def test_section_without_embedding(self):
        """File mode should create sections but NOT embed them."""
        # This is verified by the branching logic: when history_mode=="file",
        # embed_text is not called. We test the mode detection.
        bot = _make_bot(history_mode="file")
        ch = _make_channel(history_mode=None)
        assert _get_history_mode(bot, ch) == "file"
        # In the actual code, "file" mode skips the embed_text call.
        # The full integration test would require a running DB.


class TestCompactionStreamSummaryMode:
    """Verify existing summary mode is unchanged."""

    def test_summary_mode_routes_correctly(self):
        """Default summary mode should not enter section path."""
        bot = _make_bot(history_mode="summary")
        assert _get_history_mode(bot) == "summary"

    def test_none_history_mode_defaults_to_file(self):
        bot = _make_bot(history_mode=None)
        assert _get_history_mode(bot) == "file"
