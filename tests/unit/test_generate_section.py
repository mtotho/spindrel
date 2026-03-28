"""Tests for _generate_section() and _regenerate_executive_summary()."""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.compaction import _generate_section, _regenerate_executive_summary


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


class TestGenerateSection:
    @pytest.mark.asyncio
    async def test_returns_title_summary_and_deterministic_transcript(self):
        """LLM returns title/summary/tags; transcript is built from raw messages."""
        llm_json = json.dumps({
            "title": "Setting Up Slack",
            "summary": "User configured Slack integration with socket mode.",
            "tags": ["slack", "integration"],
        })
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response(llm_json)
        )
        conversation = [
            {"role": "user", "content": "Let's set up Slack"},
            {"role": "assistant", "content": "I'll help."},
        ]
        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            title, summary, transcript, tags = await _generate_section(conversation, "gpt-4")
        assert title == "Setting Up Slack"
        assert "socket mode" in summary
        # Transcript is deterministic from raw messages, not LLM output
        assert "[USER]: Let's set up Slack" in transcript
        assert "[ASSISTANT]: I'll help." in transcript
        assert tags == ["slack", "integration"]

    @pytest.mark.asyncio
    async def test_handles_markdown_fenced_json(self):
        """LLM wraps JSON in ```json fences -> still parsed."""
        raw = '```json\n{"title":"Test","summary":"s","tags":["t"]}\n```'
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response(raw)
        )
        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            title, summary, transcript, tags = await _generate_section([], "gpt-4")
        assert title == "Test"
        assert summary == "s"
        assert tags == ["t"]
        # Empty conversation -> empty transcript
        assert transcript == ""

    @pytest.mark.asyncio
    async def test_non_json_response_fallback(self):
        """LLM returns non-JSON on both tiers -> deterministic fallback."""
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response("Just a plain text summary")
        )
        conversation = [{"role": "user", "content": "hello"}]
        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            title, summary, transcript, tags = await _generate_section(conversation, "gpt-4")
        # With 3-tier escalation, both normal+aggressive fail (non-JSON),
        # so deterministic fallback uses first user message as title
        assert title == "hello"
        assert summary == "Auto-archived conversation segment."
        assert tags == ["auto-truncated"]
        # Transcript is from raw messages, not LLM
        assert "[USER]: hello" in transcript

    @pytest.mark.asyncio
    async def test_conversation_messages_included_in_prompt(self):
        """Verify the conversation messages are passed to the LLM."""
        mock_client = MagicMock()
        mock_create = AsyncMock(return_value=_mock_llm_response(
            json.dumps({"title": "T", "summary": "S", "tags": []})
        ))
        mock_client.chat.completions.create = mock_create
        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            await _generate_section(
                [{"role": "user", "content": "specific content here"}],
                "gpt-4",
            )
        call_args = mock_create.call_args
        messages = call_args.kwargs.get("messages", call_args[1].get("messages", []))
        prompt_text = " ".join(m["content"] for m in messages)
        assert "specific content here" in prompt_text

    @pytest.mark.asyncio
    async def test_empty_conversation(self):
        """Empty conversation still produces valid output."""
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response(
                json.dumps({"title": "Empty", "summary": "Nothing discussed.", "tags": []})
            )
        )
        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            title, summary, transcript, tags = await _generate_section([], "gpt-4")
        assert title == "Empty"
        assert "Nothing" in summary
        assert transcript == ""


class TestRegenerateExecutiveSummary:
    @pytest.mark.asyncio
    async def test_combines_all_section_summaries(self):
        """Verify all section titles+summaries are sent to the LLM."""
        sections = [
            MagicMock(sequence=1, title="Slack Setup", summary="Set up Slack."),
            MagicMock(sequence=2, title="Rate Limits", summary="Fixed rate limits."),
            MagicMock(sequence=3, title="File Mode", summary="Designed file mode."),
        ]
        mock_client = MagicMock()
        mock_create = AsyncMock(return_value=_mock_llm_response("Executive summary text"))
        mock_client.chat.completions.create = mock_create

        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.compaction.async_session") as mock_session:
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = sections
            mock_db.execute = AsyncMock(return_value=mock_result)
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _regenerate_executive_summary(uuid.uuid4(), "gpt-4")

        assert result == "Executive summary text"
        call_args = mock_create.call_args
        messages = call_args.kwargs.get("messages", call_args[1].get("messages", []))
        prompt_text = " ".join(m["content"] for m in messages)
        assert "Slack Setup" in prompt_text
        assert "Rate Limits" in prompt_text
        assert "File Mode" in prompt_text

    @pytest.mark.asyncio
    async def test_no_sections_returns_empty(self):
        """Channel with no sections -> returns empty string."""
        mock_client = MagicMock()
        with patch("app.services.providers.get_llm_client", return_value=mock_client), \
             patch("app.services.compaction.async_session") as mock_session:
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_db.execute = AsyncMock(return_value=mock_result)
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await _regenerate_executive_summary(uuid.uuid4(), "gpt-4")
        assert result == ""
