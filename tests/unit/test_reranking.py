"""Tests for app.services.reranking."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.reranking import (
    CHUNK_SEPARATOR,
    RerankResult,
    _identify_rag_messages,
    _parse_keep_indices,
    rerank_rag_context,
)


# ---------------------------------------------------------------------------
# _identify_rag_messages
# ---------------------------------------------------------------------------

class TestIdentifyRagMessages:
    def test_skill_pinned(self):
        messages = [
            {"role": "system", "content": "Pinned skill context:\n\nChunk A\n\n---\n\nChunk B"},
        ]
        result = _identify_rag_messages(messages)
        assert len(result) == 1
        assert result[0].source == "skill_pinned"
        assert len(result[0].chunks) == 2

    def test_memory(self):
        messages = [
            {"role": "system", "content": "Relevant memories from past conversations (automatically recalled):\n\nmem1\n\n---\n\nmem2"},
        ]
        result = _identify_rag_messages(messages)
        assert len(result) == 1
        assert result[0].source == "memory"
        assert len(result[0].chunks) == 2

    def test_tagged_excluded(self):
        messages = [
            {"role": "system", "content": "Tagged skill context (explicitly requested):\n\nSome content"},
            {"role": "system", "content": "Tagged knowledge (explicitly requested):\n\nSome knowledge"},
        ]
        result = _identify_rag_messages(messages)
        assert len(result) == 0

    def test_non_system_ignored(self):
        messages = [
            {"role": "user", "content": "Pinned skill context:\n\nChunk A"},
        ]
        result = _identify_rag_messages(messages)
        assert len(result) == 0

    def test_knowledge_rag(self):
        messages = [
            {"role": "system", "content": "Relevant knowledge:\n\ndoc1\n\n---\n\ndoc2\n\n---\n\ndoc3"},
        ]
        result = _identify_rag_messages(messages)
        assert len(result) == 1
        assert result[0].source == "knowledge"
        assert len(result[0].chunks) == 3

    def test_filesystem(self):
        messages = [
            {"role": "system", "content": "Relevant code/files from indexed directories (hint: use exec_command):\n\nfile1\n\n---\n\nfile2"},
        ]
        result = _identify_rag_messages(messages)
        assert len(result) == 1
        assert result[0].source == "filesystem"

    def test_multiple_sources(self):
        messages = [
            {"role": "system", "content": "Base system prompt"},
            {"role": "system", "content": "Pinned skill context:\n\nskill_chunk"},
            {"role": "system", "content": "Relevant memories from past conversations:\n\nmem_chunk"},
            {"role": "system", "content": "Relevant knowledge:\n\nknowledge_chunk"},
            {"role": "user", "content": "hello"},
        ]
        result = _identify_rag_messages(messages)
        assert len(result) == 3
        sources = {r.source for r in result}
        assert sources == {"skill_pinned", "memory", "knowledge"}


# ---------------------------------------------------------------------------
# _parse_keep_indices
# ---------------------------------------------------------------------------

class TestParseKeepIndices:
    def test_valid_json(self):
        assert _parse_keep_indices('{"keep": [0, 2, 5]}', 10) == [0, 2, 5]

    def test_with_markdown_fences(self):
        assert _parse_keep_indices('```json\n{"keep": [1, 3]}\n```', 10) == [1, 3]

    def test_invalid_indices_filtered(self):
        assert _parse_keep_indices('{"keep": [0, 100, -1, 2]}', 10) == [0, 2]

    def test_garbage(self):
        assert _parse_keep_indices("no json here", 10) is None

    def test_missing_keep_key(self):
        assert _parse_keep_indices('{"result": [0, 1]}', 10) is None

    def test_json_within_text(self):
        assert _parse_keep_indices('Here are the results: {"keep": [0, 1]}', 10) == [0, 1]


# ---------------------------------------------------------------------------
# rerank_rag_context
# ---------------------------------------------------------------------------

class TestRerankRagContext:
    @pytest.mark.asyncio
    async def test_disabled(self):
        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = False
            result = await rerank_rag_context([], "query")
            assert result is None

    @pytest.mark.asyncio
    async def test_below_threshold(self):
        messages = [
            {"role": "system", "content": "Pinned skill context:\n\nshort"},
        ]
        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 99999
            result = await rerank_rag_context(messages, "query")
            assert result is None

    @pytest.mark.asyncio
    async def test_successful_rerank(self):
        chunk_a = "A" * 2000
        chunk_b = "B" * 2000
        chunk_c = "C" * 2000
        messages = [
            {"role": "system", "content": "Base prompt"},
            {"role": "system", "content": f"Pinned skill context:\n\n{chunk_a}{CHUNK_SEPARATOR}{chunk_b}"},
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk_c}"},
            {"role": "user", "content": "hello"},
        ]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"keep": [0, 2]}'

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_CHUNKS = 20
            mock_settings.RAG_RERANK_MAX_TOKENS = 1000
            mock_settings.RAG_RERANK_MODEL = "test-model"
            mock_settings.COMPACTION_MODEL = "fallback-model"

            with patch("app.services.providers.get_llm_client", return_value=mock_client):
                result = await rerank_rag_context(messages, "test query")

        assert result is not None
        assert result.original_chunks == 3
        assert result.kept_chunks == 2  # chunk_a (idx 0) + chunk_c (idx 2)
        # chunk_b (idx 1) was removed from skill message
        assert len(messages) == 4  # base prompt, skill (trimmed), knowledge, user

    @pytest.mark.asyncio
    async def test_removes_empty_messages(self):
        chunk_a = "A" * 3000
        chunk_b = "B" * 3000
        messages = [
            {"role": "system", "content": "Base prompt"},
            {"role": "system", "content": f"Pinned skill context:\n\n{chunk_a}"},
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk_b}"},
            {"role": "user", "content": "hello"},
        ]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"keep": [0]}'  # keep only first chunk

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_CHUNKS = 20
            mock_settings.RAG_RERANK_MAX_TOKENS = 1000
            mock_settings.RAG_RERANK_MODEL = ""
            mock_settings.COMPACTION_MODEL = "fallback-model"

            with patch("app.services.providers.get_llm_client", return_value=mock_client):
                result = await rerank_rag_context(messages, "test query")

        assert result is not None
        assert result.kept_chunks == 1
        # knowledge message should be removed (no surviving chunks)
        assert len(messages) == 3  # base prompt, skill, user

    @pytest.mark.asyncio
    async def test_llm_error_returns_none(self):
        chunk = "A" * 6000
        messages = [
            {"role": "system", "content": f"Pinned skill context:\n\n{chunk}"},
        ]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("LLM error"))

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_TOKENS = 1000
            mock_settings.RAG_RERANK_MODEL = "test-model"
            mock_settings.COMPACTION_MODEL = "fallback"

            with patch("app.services.providers.get_llm_client", return_value=mock_client):
                result = await rerank_rag_context(messages, "query")

        assert result is None

    @pytest.mark.asyncio
    async def test_parse_error_returns_none(self):
        chunk = "A" * 6000
        messages = [
            {"role": "system", "content": f"Pinned skill context:\n\n{chunk}"},
        ]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "not json at all!!"

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_CHUNKS = 20
            mock_settings.RAG_RERANK_MAX_TOKENS = 1000
            mock_settings.RAG_RERANK_MODEL = "test-model"
            mock_settings.COMPACTION_MODEL = "fallback"

            with patch("app.services.providers.get_llm_client", return_value=mock_client):
                result = await rerank_rag_context(messages, "query")

        assert result is None
