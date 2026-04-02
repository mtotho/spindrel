"""Tests for app.services.summarizer — config resolution, message fetching, LLM call."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.summarizer import _resolve_model, summarize_messages

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _channel(**overrides) -> MagicMock:
    ch = MagicMock()
    ch.id = overrides.get("id", uuid.uuid4())
    ch.compaction_model = overrides.get("compaction_model", None)
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
    def test_channel_compaction_model(self, mock_settings):
        ch = _channel(compaction_model="compaction-chan")
        assert _resolve_model(ch) == "compaction-chan"

    @patch("app.services.summarizer.settings")
    def test_global_compaction_model_fallback(self, mock_settings):
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

    async def test_param_prompt_used(self):
        """Explicit prompt param is used in the LLM call."""
        ch = _channel()
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
