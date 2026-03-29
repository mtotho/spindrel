"""Tests for app.agent.rag.retrieve_context — tuple indexing and threshold filtering."""
from unittest.mock import patch, AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# retrieve_context: correct tuple indexing after (content, source, distance) change
# ---------------------------------------------------------------------------

class TestRetrieveContextTupleIndexing:
    """Regression: rows are (content, source, distance) — distance is at index 2."""

    @pytest.mark.asyncio
    @patch("app.agent.rag.async_session")
    @patch("app.agent.rag.embed_text", new_callable=AsyncMock, return_value=[0.1] * 1536)
    async def test_best_similarity_uses_distance_not_source(self, _mock_embed, mock_session_cls):
        """Ensure best_distance reads from rows[0][2] (distance), not rows[0][1] (source string).

        Before the fix, rows[0][1] was the source string, causing:
            TypeError: unsupported operand type(s) for -: 'float' and 'str'
        """
        # Simulate DB rows: (content, source, distance)
        fake_rows = [
            ("chunk about APIs", "skill:api-guide", 0.15),   # similarity = 0.85
            ("chunk about auth", "skill:auth-guide", 0.30),   # similarity = 0.70
        ]
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = fake_rows
        mock_db.execute.return_value = mock_result
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from app.agent.rag import retrieve_context
        chunks, best_sim = await retrieve_context("how do APIs work?", skill_ids=["api-guide"])

        # best_similarity should be 1.0 - 0.15 = 0.85, not a TypeError
        assert abs(best_sim - 0.85) < 0.001
        # Both chunks above default threshold (0.3)
        assert len(chunks) == 2
        assert chunks[0] == ("chunk about APIs", "skill:api-guide")
        assert chunks[1] == ("chunk about auth", "skill:auth-guide")

    @pytest.mark.asyncio
    @patch("app.agent.rag.async_session")
    @patch("app.agent.rag.embed_text", new_callable=AsyncMock, return_value=[0.1] * 1536)
    async def test_threshold_filtering(self, _mock_embed, mock_session_cls):
        """Chunks below similarity threshold are excluded."""
        fake_rows = [
            ("good chunk", "skill:s1", 0.10),   # sim = 0.90 — above
            ("bad chunk", "skill:s2", 0.80),     # sim = 0.20 — below default 0.3
        ]
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = fake_rows
        mock_db.execute.return_value = mock_result
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from app.agent.rag import retrieve_context
        chunks, best_sim = await retrieve_context("query", similarity_threshold=0.5)

        assert len(chunks) == 1
        assert chunks[0][0] == "good chunk"

    @pytest.mark.asyncio
    @patch("app.agent.rag.async_session")
    @patch("app.agent.rag.embed_text", new_callable=AsyncMock, return_value=[0.1] * 1536)
    async def test_no_rows_returns_empty(self, _mock_embed, mock_session_cls):
        """Empty result set returns ([], 0.0)."""
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result
        mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from app.agent.rag import retrieve_context
        chunks, best_sim = await retrieve_context("query")

        assert chunks == []
        assert best_sim == 0.0

    @pytest.mark.asyncio
    @patch("app.agent.rag.embed_text", new_callable=AsyncMock, side_effect=Exception("embed failed"))
    async def test_embed_failure_returns_empty(self, _mock_embed):
        """Embedding failure returns ([], 0.0) gracefully."""
        from app.agent.rag import retrieve_context
        chunks, best_sim = await retrieve_context("query")

        assert chunks == []
        assert best_sim == 0.0
