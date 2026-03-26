"""Tests for app.agent.embeddings — truncation safety."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.embeddings import _truncate, _MAX_EMBED_CHARS


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello") == "hello"

    def test_exact_limit_unchanged(self):
        text = "x" * _MAX_EMBED_CHARS
        assert _truncate(text) == text

    def test_over_limit_truncated(self):
        text = "x" * (_MAX_EMBED_CHARS + 5000)
        result = _truncate(text)
        assert len(result) == _MAX_EMBED_CHARS

    def test_empty_string(self):
        assert _truncate("") == ""


class TestEmbedTextTruncation:
    @pytest.mark.asyncio
    async def test_large_input_truncated_before_api_call(self):
        from app.agent.embeddings import embed_text

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 10)]

        with patch("app.agent.embeddings._client") as mock_client:
            mock_client.embeddings.create = AsyncMock(return_value=mock_response)
            await embed_text("x" * 100_000)

        sent_input = mock_client.embeddings.create.call_args.kwargs["input"][0]
        assert len(sent_input) == _MAX_EMBED_CHARS


class TestEmbedBatchTruncation:
    @pytest.mark.asyncio
    async def test_large_items_truncated(self):
        from app.agent.embeddings import embed_batch

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 10), MagicMock(embedding=[0.2] * 10)]

        with patch("app.agent.embeddings._client") as mock_client:
            mock_client.embeddings.create = AsyncMock(return_value=mock_response)
            await embed_batch(["x" * 100_000, "short"])

        sent_input = mock_client.embeddings.create.call_args.kwargs["input"]
        assert len(sent_input[0]) == _MAX_EMBED_CHARS
        assert sent_input[1] == "short"
