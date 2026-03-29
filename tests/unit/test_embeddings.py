"""Tests for app.agent.embeddings — truncation safety + zero-padding + local routing."""
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.embeddings import _truncate, _zero_pad, _MAX_EMBED_CHARS


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


class TestZeroPad:
    def test_shorter_vector_padded(self):
        vec = [1.0, 2.0, 3.0]
        result = _zero_pad(vec, 6)
        assert result == [1.0, 2.0, 3.0, 0.0, 0.0, 0.0]
        assert len(result) == 6

    def test_exact_length_unchanged(self):
        vec = [1.0, 2.0, 3.0]
        result = _zero_pad(vec, 3)
        assert result == vec

    def test_longer_vector_unchanged(self):
        vec = [1.0, 2.0, 3.0]
        result = _zero_pad(vec, 2)
        assert result == vec

    def test_empty_vector(self):
        assert _zero_pad([], 3) == [0.0, 0.0, 0.0]

    def test_cosine_similarity_preserved(self):
        """Zero-padding preserves cosine similarity between same-model vectors."""
        a = [0.3, 0.5, 0.8]
        b = [0.1, 0.9, 0.4]

        def cosine_sim(x, y):
            dot = sum(xi * yi for xi, yi in zip(x, y))
            norm_x = math.sqrt(sum(xi ** 2 for xi in x))
            norm_y = math.sqrt(sum(yi ** 2 for yi in y))
            return dot / (norm_x * norm_y)

        orig_sim = cosine_sim(a, b)
        padded_sim = cosine_sim(_zero_pad(a, 10), _zero_pad(b, 10))
        assert abs(orig_sim - padded_sim) < 1e-10


class TestLocalModelRouting:
    @pytest.mark.asyncio
    async def test_embed_text_routes_to_local(self):
        """embed_text with a local/ model calls embed_local_sync, not _client."""
        from app.agent.embeddings import embed_text

        fake_vectors = [[0.1, 0.2, 0.3]]

        with (
            patch("app.agent.embeddings.embed_local_sync", return_value=fake_vectors) as mock_local,
            patch("app.agent.embeddings._client") as mock_client,
            patch("app.agent.embeddings.settings") as mock_settings,
        ):
            mock_settings.EMBEDDING_DIMENSIONS = 6
            result = await embed_text("hello", model="local/BAAI/bge-small-en-v1.5")

        mock_local.assert_called_once()
        mock_client.embeddings.create.assert_not_called()
        # Should be zero-padded to 6 dims
        assert len(result) == 6
        assert result[:3] == [0.1, 0.2, 0.3]
        assert result[3:] == [0.0, 0.0, 0.0]

    @pytest.mark.asyncio
    async def test_embed_batch_routes_to_local(self):
        """embed_batch with a local/ model calls embed_local_sync, not _client."""
        from app.agent.embeddings import embed_batch

        fake_vectors = [[0.1, 0.2], [0.3, 0.4]]

        with (
            patch("app.agent.embeddings.embed_local_sync", return_value=fake_vectors) as mock_local,
            patch("app.agent.embeddings._client") as mock_client,
            patch("app.agent.embeddings.settings") as mock_settings,
        ):
            mock_settings.EMBEDDING_DIMENSIONS = 4
            result = await embed_batch(["hello", "world"], model="local/BAAI/bge-small-en-v1.5")

        mock_local.assert_called_once()
        mock_client.embeddings.create.assert_not_called()
        assert len(result) == 2
        assert len(result[0]) == 4
        assert len(result[1]) == 4

    @pytest.mark.asyncio
    async def test_non_local_model_uses_client(self):
        """Non-local models still go through the OpenAI client."""
        from app.agent.embeddings import embed_text

        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 10)]

        with (
            patch("app.agent.embeddings.embed_local_sync") as mock_local,
            patch("app.agent.embeddings._client") as mock_client,
        ):
            mock_client.embeddings.create = AsyncMock(return_value=mock_response)
            await embed_text("hello", model="text-embedding-3-small")

        mock_local.assert_not_called()
        mock_client.embeddings.create.assert_called_once()
