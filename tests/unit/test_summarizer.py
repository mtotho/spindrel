"""Tests for app.services.summarizer — config resolution, message fetching, LLM call."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.summarizer import _resolve_model, summarize_messages, get_last_user_message_time

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _channel(**overrides) -> MagicMock:
    ch = MagicMock()
    ch.id = overrides.get("id", uuid.uuid4())
    ch.summarizer_model = overrides.get("summarizer_model", None)
    ch.compression_model = overrides.get("compression_model", None)
    ch.summarizer_message_count = overrides.get("summarizer_message_count", None)
    ch.summarizer_target_size = overrides.get("summarizer_target_size", None)
    ch.summarizer_prompt = overrides.get("summarizer_prompt", None)
    return ch


class FakeMessage:
    def __init__(self, role="user", content="Hello", created_at=None):
        self.role = role
        self.content = content
        self.created_at = created_at or datetime.now(timezone.utc)


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    """Async context-manager DB session stub that can return different results per call."""

    def __init__(self, results=None):
        self._results = results or []
        self._call_idx = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def execute(self, stmt):
        if self._call_idx < len(self._results):
            result = self._results[self._call_idx]
            self._call_idx += 1
            return result
        return FakeResult([])


# ---------------------------------------------------------------------------
# _resolve_model
# ---------------------------------------------------------------------------

class TestResolveModel:
    @patch("app.services.summarizer.settings")
    def test_channel_summarizer_model_wins(self, mock_settings):
        ch = _channel(summarizer_model="summarizer-model")
        assert _resolve_model(ch) == "summarizer-model"

    @patch("app.services.summarizer.settings")
    def test_channel_compression_model_fallback(self, mock_settings):
        ch = _channel(compression_model="compression-model")
        assert _resolve_model(ch) == "compression-model"

    @patch("app.services.summarizer.settings")
    def test_global_summarizer_model(self, mock_settings):
        mock_settings.SUMMARIZER_MODEL = "global-summarizer"
        mock_settings.CONTEXT_COMPRESSION_MODEL = ""
        mock_settings.COMPACTION_MODEL = "compaction"
        assert _resolve_model(None) == "global-summarizer"

    @patch("app.services.summarizer.settings")
    def test_global_compression_model_fallback(self, mock_settings):
        mock_settings.SUMMARIZER_MODEL = ""
        mock_settings.CONTEXT_COMPRESSION_MODEL = "global-compression"
        mock_settings.COMPACTION_MODEL = "compaction"
        assert _resolve_model(None) == "global-compression"

    @patch("app.services.summarizer.settings")
    def test_compaction_model_last_resort(self, mock_settings):
        mock_settings.SUMMARIZER_MODEL = ""
        mock_settings.CONTEXT_COMPRESSION_MODEL = ""
        mock_settings.COMPACTION_MODEL = "compaction-model"
        assert _resolve_model(None) == "compaction-model"


# ---------------------------------------------------------------------------
# summarize_messages
# ---------------------------------------------------------------------------

class TestSummarizeMessages:
    async def test_channel_not_found(self):
        ch_id = uuid.uuid4()
        session = FakeSession(results=[FakeResult([])])  # no channel
        with patch("app.services.summarizer.async_session", return_value=session):
            result = await summarize_messages(ch_id)
        assert "Error: channel not found" in result

    async def test_no_messages_returns_info(self):
        ch = _channel()
        ch_id = ch.id
        # First call: channel lookup; second call: message query
        session_for_channel = FakeSession(results=[FakeResult([ch])])
        session_for_messages = FakeSession(results=[FakeResult([])])

        with patch("app.services.summarizer.async_session", side_effect=[
            session_for_channel, session_for_messages,
        ]):
            result = await summarize_messages(ch_id)
        assert "No messages found" in result

    async def test_successful_summary(self):
        ch = _channel()
        ch_id = ch.id
        msgs = [
            FakeMessage(role="user", content="Hello"),
            FakeMessage(role="assistant", content="Hi there"),
        ]

        session_for_channel = FakeSession(results=[FakeResult([ch])])
        session_for_messages = FakeSession(results=[FakeResult(msgs)])

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Summary: User greeted, assistant replied."

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with (
            patch("app.services.summarizer.async_session", side_effect=[
                session_for_channel, session_for_messages,
            ]),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
        ):
            result = await summarize_messages(ch_id)

        assert "Summary: User greeted" in result
        mock_client.chat.completions.create.assert_called_once()

    async def test_llm_failure_returns_error(self):
        ch = _channel()
        ch_id = ch.id
        msgs = [FakeMessage()]

        session_for_channel = FakeSession(results=[FakeResult([ch])])
        session_for_messages = FakeSession(results=[FakeResult(msgs)])

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API down"))

        with (
            patch("app.services.summarizer.async_session", side_effect=[
                session_for_channel, session_for_messages,
            ]),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
        ):
            result = await summarize_messages(ch_id)

        assert "Error:" in result

    async def test_channel_defaults_used(self):
        """Channel-level defaults for target_size and prompt are used when no params given."""
        ch = _channel(
            summarizer_target_size=500,
            summarizer_prompt="Focus on action items",
            summarizer_message_count=50,
        )
        ch_id = ch.id
        msgs = [FakeMessage(role="user", content="Test")]

        session_for_channel = FakeSession(results=[FakeResult([ch])])
        session_for_messages = FakeSession(results=[FakeResult(msgs)])

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Focused summary."

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with (
            patch("app.services.summarizer.async_session", side_effect=[
                session_for_channel, session_for_messages,
            ]),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
        ):
            result = await summarize_messages(ch_id)

        # Verify the LLM was called with a prompt containing the target size
        call_args = mock_client.chat.completions.create.call_args
        system_prompt = call_args.kwargs["messages"][0]["content"]
        assert "500" in system_prompt
        assert "Focus on action items" in system_prompt

    async def test_param_prompt_overrides_channel(self):
        """Explicit prompt param takes precedence over channel.summarizer_prompt."""
        ch = _channel(summarizer_prompt="Channel default")
        ch_id = ch.id
        msgs = [FakeMessage(role="user", content="Test")]

        session_for_channel = FakeSession(results=[FakeResult([ch])])
        session_for_messages = FakeSession(results=[FakeResult(msgs)])

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Custom summary."

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with (
            patch("app.services.summarizer.async_session", side_effect=[
                session_for_channel, session_for_messages,
            ]),
            patch("app.services.providers.get_llm_client", return_value=mock_client),
        ):
            result = await summarize_messages(ch_id, prompt="What about the database?")

        call_args = mock_client.chat.completions.create.call_args
        system_prompt = call_args.kwargs["messages"][0]["content"]
        assert "What about the database?" in system_prompt
        assert "Channel default" not in system_prompt


# ---------------------------------------------------------------------------
# get_last_user_message_time
# ---------------------------------------------------------------------------

class TestGetLastUserMessageTime:
    async def test_returns_timestamp(self):
        ts = datetime(2026, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
        session = FakeSession(results=[FakeResult([ts])])

        with patch("app.services.summarizer.async_session", return_value=session):
            result = await get_last_user_message_time(uuid.uuid4())
        assert result == ts

    async def test_returns_none_for_empty_channel(self):
        session = FakeSession(results=[FakeResult([])])

        with patch("app.services.summarizer.async_session", return_value=session):
            result = await get_last_user_message_time(uuid.uuid4())
        assert result is None
