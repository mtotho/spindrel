"""Tests for app.services.response_condensing — threshold, condensing, model resolution."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.response_condensing import _resolve_model, condense_response

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _channel(**overrides) -> MagicMock:
    ch = MagicMock()
    ch.id = overrides.get("id", uuid.uuid4())
    ch.response_condensing_enabled = overrides.get("response_condensing_enabled", True)
    ch.response_condensing_threshold = overrides.get("response_condensing_threshold", None)
    ch.response_condensing_keep_exact = overrides.get("response_condensing_keep_exact", None)
    ch.response_condensing_model = overrides.get("response_condensing_model", None)
    ch.response_condensing_prompt = overrides.get("response_condensing_prompt", None)
    ch.compression_model = overrides.get("compression_model", None)
    return ch


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def execute(self, stmt):
        pass

    async def commit(self):
        pass


# ---------------------------------------------------------------------------
# _resolve_model
# ---------------------------------------------------------------------------

class TestResolveModel:
    @patch("app.services.response_condensing.settings")
    def test_channel_model_wins(self, mock_settings):
        ch = _channel(response_condensing_model="fast-model")
        assert _resolve_model(ch) == "fast-model"

    @patch("app.services.response_condensing.settings")
    def test_global_condensing_model(self, mock_settings):
        mock_settings.RESPONSE_CONDENSING_MODEL = "global-condenser"
        mock_settings.CONTEXT_COMPRESSION_MODEL = ""
        mock_settings.COMPACTION_MODEL = "compaction"
        ch = _channel()
        assert _resolve_model(ch) == "global-condenser"

    @patch("app.services.response_condensing.settings")
    def test_compression_model_fallback(self, mock_settings):
        mock_settings.RESPONSE_CONDENSING_MODEL = ""
        mock_settings.CONTEXT_COMPRESSION_MODEL = "compression-model"
        mock_settings.COMPACTION_MODEL = "compaction"
        ch = _channel()
        assert _resolve_model(ch) == "compression-model"

    @patch("app.services.response_condensing.settings")
    def test_compaction_model_last_resort(self, mock_settings):
        mock_settings.RESPONSE_CONDENSING_MODEL = ""
        mock_settings.CONTEXT_COMPRESSION_MODEL = ""
        mock_settings.COMPACTION_MODEL = "compaction-model"
        ch = _channel()
        assert _resolve_model(ch) == "compaction-model"


# ---------------------------------------------------------------------------
# condense_response
# ---------------------------------------------------------------------------

class TestCondenseResponse:
    async def test_below_threshold_returns_none(self):
        ch = _channel(response_condensing_threshold=2000)
        result = await condense_response(uuid.uuid4(), "Short text", ch)
        assert result is None

    async def test_uses_default_threshold(self):
        """When channel has no threshold, uses global default (1500)."""
        ch = _channel(response_condensing_threshold=None)
        # Content below default threshold of 1500
        result = await condense_response(uuid.uuid4(), "x" * 1000, ch)
        assert result is None

    @patch("app.services.response_condensing.settings")
    async def test_successful_condensing(self, mock_settings):
        mock_settings.RESPONSE_CONDENSING_THRESHOLD = 100
        mock_settings.RESPONSE_CONDENSING_MODEL = ""
        mock_settings.CONTEXT_COMPRESSION_MODEL = ""
        mock_settings.COMPACTION_MODEL = "test-model"

        ch = _channel(response_condensing_threshold=100)
        msg_id = uuid.uuid4()
        long_content = "x" * 200

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Condensed version"

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with (
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.services.response_condensing.async_session", return_value=FakeSession()),
        ):
            result = await condense_response(msg_id, long_content, ch)

        assert result == "Condensed version"
        mock_client.chat.completions.create.assert_called_once()

    @patch("app.services.response_condensing.settings")
    async def test_llm_failure_returns_none(self, mock_settings):
        mock_settings.RESPONSE_CONDENSING_THRESHOLD = 100
        mock_settings.RESPONSE_CONDENSING_MODEL = ""
        mock_settings.CONTEXT_COMPRESSION_MODEL = ""
        mock_settings.COMPACTION_MODEL = "test-model"

        ch = _channel(response_condensing_threshold=100)
        msg_id = uuid.uuid4()

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("API down"))

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            result = await condense_response(msg_id, "x" * 200, ch)

        assert result is None

    @patch("app.services.response_condensing.settings")
    async def test_custom_prompt_appended(self, mock_settings):
        mock_settings.RESPONSE_CONDENSING_THRESHOLD = 100
        mock_settings.RESPONSE_CONDENSING_MODEL = ""
        mock_settings.CONTEXT_COMPRESSION_MODEL = ""
        mock_settings.COMPACTION_MODEL = "test-model"

        ch = _channel(
            response_condensing_threshold=100,
            response_condensing_prompt="Always preserve code blocks",
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Condensed"

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with (
            patch("app.services.providers.get_llm_client", return_value=mock_client),
            patch("app.services.response_condensing.async_session", return_value=FakeSession()),
        ):
            await condense_response(uuid.uuid4(), "x" * 200, ch)

        call_args = mock_client.chat.completions.create.call_args
        system_prompt = call_args.kwargs["messages"][0]["content"]
        assert "Always preserve code blocks" in system_prompt

    @patch("app.services.response_condensing.settings")
    async def test_empty_condensed_returns_none(self, mock_settings):
        mock_settings.RESPONSE_CONDENSING_THRESHOLD = 100
        mock_settings.RESPONSE_CONDENSING_MODEL = ""
        mock_settings.CONTEXT_COMPRESSION_MODEL = ""
        mock_settings.COMPACTION_MODEL = "test-model"

        ch = _channel(response_condensing_threshold=100)

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "   "

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.providers.get_llm_client", return_value=mock_client):
            result = await condense_response(uuid.uuid4(), "x" * 200, ch)

        assert result is None


# ---------------------------------------------------------------------------
# Keep-exact window (condensing boundary)
# ---------------------------------------------------------------------------

class TestCondensingBoundary:
    def test_no_channel(self):
        from app.services.sessions import _condensing_boundary
        msgs = [MagicMock() for _ in range(10)]
        assert _condensing_boundary(msgs, None) == 0

    def test_condensing_disabled(self):
        from app.services.sessions import _condensing_boundary
        ch = _channel(response_condensing_enabled=False)
        ch.response_condensing_enabled = False
        msgs = [MagicMock() for _ in range(10)]
        assert _condensing_boundary(msgs, ch) == 0

    @patch("app.config.settings")
    def test_keep_exact_from_channel(self, mock_settings):
        from app.services.sessions import _condensing_boundary
        mock_settings.RESPONSE_CONDENSING_KEEP_EXACT = 6
        ch = _channel(response_condensing_keep_exact=3)
        msgs = [MagicMock() for _ in range(10)]
        # boundary should be 10 - 3 = 7
        assert _condensing_boundary(msgs, ch) == 7

    @patch("app.config.settings")
    def test_keep_exact_from_global(self, mock_settings):
        from app.services.sessions import _condensing_boundary
        mock_settings.RESPONSE_CONDENSING_KEEP_EXACT = 4
        ch = _channel(response_condensing_keep_exact=None)
        msgs = [MagicMock() for _ in range(10)]
        # boundary should be 10 - 4 = 6
        assert _condensing_boundary(msgs, ch) == 6

    @patch("app.config.settings")
    def test_all_within_window(self, mock_settings):
        from app.services.sessions import _condensing_boundary
        mock_settings.RESPONSE_CONDENSING_KEEP_EXACT = 20
        ch = _channel(response_condensing_keep_exact=None)
        msgs = [MagicMock() for _ in range(5)]
        # 5 messages but keep_exact=20, so boundary=0
        assert _condensing_boundary(msgs, ch) == 0
