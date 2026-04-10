"""Tests for app.services.reranking."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.reranking import (
    CHUNK_SEPARATOR,
    RerankResult,
    _identify_rag_messages,
    _parse_keep_indices,
    _sigmoid,
    rerank_rag_context,
)


# ---------------------------------------------------------------------------
# _sigmoid
# ---------------------------------------------------------------------------

class TestSigmoid:
    def test_zero_gives_half(self):
        assert _sigmoid(0.0) == 0.5

    def test_large_positive_near_one(self):
        assert _sigmoid(10.0) > 0.9999

    def test_large_negative_near_zero(self):
        assert _sigmoid(-10.0) < 0.0001

    def test_known_values(self):
        # sigmoid(2) ≈ 0.8808
        assert abs(_sigmoid(2.0) - 0.8808) < 0.001
        # sigmoid(-2) ≈ 0.1192
        assert abs(_sigmoid(-2.0) - 0.1192) < 0.001

    def test_overflow_protection(self):
        # Extreme values shouldn't crash
        assert _sigmoid(-1000) == 0.0
        assert _sigmoid(1000) == 1.0

    def test_threshold_boundary(self):
        """logit of -4.6 gives sigmoid ≈ 0.01 (the default threshold)."""
        assert abs(_sigmoid(-4.6) - 0.01) < 0.002


# ---------------------------------------------------------------------------
# _identify_rag_messages
# ---------------------------------------------------------------------------

class TestIdentifyRagMessages:
    def test_pinned_skill_excluded(self):
        """Pinned skills are never reranked — they should be excluded."""
        messages = [
            {"role": "system", "content": "Pinned skill context:\n\nChunk A\n\n---\n\nChunk B"},
        ]
        result = _identify_rag_messages(messages)
        assert len(result) == 0

    def test_pinned_knowledge_excluded(self):
        """Pinned knowledge is never reranked — should be excluded."""
        messages = [
            {"role": "system", "content": "Pinned knowledge (always available):\n\ndoc1\n\n---\n\ndoc2"},
        ]
        result = _identify_rag_messages(messages)
        assert len(result) == 0

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
            {"role": "user", "content": "Relevant knowledge:\n\nChunk A"},
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
            {"role": "system", "content": "Pinned skill context:\n\nskill_chunk"},  # excluded (pinned)
            {"role": "system", "content": "Relevant knowledge:\n\nknowledge_chunk"},
            {"role": "system", "content": "Relevant memories from past conversations:\n\nmem_chunk"},
            {"role": "system", "content": "Relevant code/files from indexed directories:\n\nfile_chunk"},
            {"role": "user", "content": "hello"},
        ]
        result = _identify_rag_messages(messages)
        assert len(result) == 3
        sources = {r.source for r in result}
        assert sources == {"knowledge", "memory", "filesystem"}

    def test_multiple_pinned_types_all_excluded(self):
        """Both pinned prefix types should be excluded from reranking."""
        messages = [
            {"role": "system", "content": "Pinned skill context:\n\nskill"},
            {"role": "system", "content": "Pinned knowledge (always available):\n\nknowledge"},
        ]
        result = _identify_rag_messages(messages)
        assert len(result) == 0


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
# rerank_rag_context — LLM backend
# ---------------------------------------------------------------------------

class TestRerankRagContextLLM:
    @pytest.mark.asyncio
    async def test_disabled(self):
        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = False
            result = await rerank_rag_context([], "query")
            assert result is None

    @pytest.mark.asyncio
    async def test_below_threshold(self):
        messages = [
            {"role": "system", "content": "Relevant knowledge:\n\nshort"},
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
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk_a}{CHUNK_SEPARATOR}{chunk_b}"},
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
            mock_settings.RAG_RERANK_BACKEND = "llm"
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_CHUNKS = 20
            mock_settings.RAG_RERANK_MAX_TOKENS = 1000
            mock_settings.RAG_RERANK_MODEL = "test-model"
            mock_settings.COMPACTION_MODEL = "fallback-model"
            mock_settings.RAG_RERANK_SCORE_THRESHOLD = 0.01

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
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk_a}"},
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
            mock_settings.RAG_RERANK_BACKEND = "llm"
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_CHUNKS = 20
            mock_settings.RAG_RERANK_MAX_TOKENS = 1000
            mock_settings.RAG_RERANK_MODEL = ""
            mock_settings.COMPACTION_MODEL = "fallback-model"
            mock_settings.RAG_RERANK_SCORE_THRESHOLD = 0.01

            with patch("app.services.providers.get_llm_client", return_value=mock_client):
                result = await rerank_rag_context(messages, "test query")

        assert result is not None
        assert result.kept_chunks == 1
        # knowledge message should be removed (no surviving chunks)
        assert len(messages) == 3  # base prompt, skill, user

    @pytest.mark.asyncio
    async def test_no_model_returns_none(self):
        """When all model settings are empty, LLM reranking skips gracefully."""
        chunk = "A" * 6000
        messages = [
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk}"},
        ]

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_BACKEND = "llm"
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_TOKENS = 1000
            mock_settings.RAG_RERANK_MODEL = ""
            mock_settings.COMPACTION_MODEL = ""
            mock_settings.DEFAULT_MODEL = ""
            mock_settings.RAG_RERANK_SCORE_THRESHOLD = 0.01

            result = await rerank_rag_context(messages, "query")

        assert result is None

    @pytest.mark.asyncio
    async def test_llm_error_returns_none(self):
        chunk = "A" * 6000
        messages = [
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk}"},
        ]

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("LLM error"))

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_BACKEND = "llm"
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_TOKENS = 1000
            mock_settings.RAG_RERANK_MODEL = "test-model"
            mock_settings.COMPACTION_MODEL = "fallback"
            mock_settings.RAG_RERANK_SCORE_THRESHOLD = 0.01

            with patch("app.services.providers.get_llm_client", return_value=mock_client):
                result = await rerank_rag_context(messages, "query")

        assert result is None

    @pytest.mark.asyncio
    async def test_parse_error_returns_none(self):
        chunk = "A" * 6000
        messages = [
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk}"},
        ]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "not json at all!!"

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_BACKEND = "llm"
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_CHUNKS = 20
            mock_settings.RAG_RERANK_MAX_TOKENS = 1000
            mock_settings.RAG_RERANK_MODEL = "test-model"
            mock_settings.COMPACTION_MODEL = "fallback"
            mock_settings.RAG_RERANK_SCORE_THRESHOLD = 0.01

            with patch("app.services.providers.get_llm_client", return_value=mock_client):
                result = await rerank_rag_context(messages, "query")

        assert result is None

    @pytest.mark.asyncio
    async def test_pinned_skills_excluded_from_llm_reranking(self):
        """Pinned skills should not be subject to LLM reranking — only RAG content is."""
        pinned_chunk = "PINNED" * 1000
        rag_chunk = "RAG" * 1000
        messages = [
            {"role": "system", "content": f"Pinned skill context:\n\n{pinned_chunk}"},
            {"role": "system", "content": f"Relevant knowledge:\n\n{rag_chunk}"},
        ]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        # LLM decides to keep index 0 (the only RAG chunk)
        mock_response.choices[0].message.content = '{"keep": [0]}'

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_BACKEND = "llm"
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_CHUNKS = 20
            mock_settings.RAG_RERANK_MAX_TOKENS = 1000
            mock_settings.RAG_RERANK_MODEL = "test-model"
            mock_settings.COMPACTION_MODEL = "fallback"
            mock_settings.RAG_RERANK_SCORE_THRESHOLD = 0.01

            with patch("app.services.providers.get_llm_client", return_value=mock_client):
                result = await rerank_rag_context(messages, "query")

        assert result is not None
        assert result.original_chunks == 1  # only RAG chunk was considered
        assert result.kept_chunks == 1
        # Both messages should still be present — pinned was never touched
        assert len(messages) == 2
        assert "PINNED" in messages[0]["content"]
        assert "RAG" in messages[1]["content"]


# ---------------------------------------------------------------------------
# rerank_rag_context — cross-encoder backend
# ---------------------------------------------------------------------------

class TestRerankRagContextCrossEncoder:
    @pytest.mark.asyncio
    async def test_cross_encoder_successful(self):
        chunk_a = "A" * 2000
        chunk_b = "B" * 2000
        chunk_c = "C" * 2000
        messages = [
            {"role": "system", "content": "Base prompt"},
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk_a}{CHUNK_SEPARATOR}{chunk_b}"},
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk_c}"},
            {"role": "user", "content": "hello"},
        ]

        # Cross-encoder returns raw logit scores: 3.0 → sigmoid ≈ 0.95,
        # -8.0 → sigmoid ≈ 0.0003 (below 0.01), 1.0 → sigmoid ≈ 0.73
        mock_rerank = AsyncMock(return_value=[3.0, -8.0, 1.0])

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_BACKEND = "cross-encoder"
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_CHUNKS = 20
            mock_settings.RAG_RERANK_CROSS_ENCODER_MODEL = "test-ce-model"
            mock_settings.RAG_RERANK_SCORE_THRESHOLD = 0.01

            with patch("app.services.cross_encoder.rerank_async", mock_rerank):
                result = await rerank_rag_context(messages, "test query")

        assert result is not None
        assert result.original_chunks == 3
        assert result.kept_chunks == 2  # chunk_a + chunk_c; chunk_b below threshold
        mock_rerank.assert_called_once()

    @pytest.mark.asyncio
    async def test_cross_encoder_sigmoid_normalization(self):
        """Cross-encoder logit scores are sigmoid-normalized before threshold comparison."""
        chunk_a = "A" * 3000
        chunk_b = "B" * 3000
        messages = [
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk_a}{CHUNK_SEPARATOR}{chunk_b}"},
        ]

        # Raw logits: -2.0 → sigmoid ≈ 0.12 (above 0.01), -6.0 → sigmoid ≈ 0.0025 (below 0.01)
        # Without sigmoid, both would be below 0.01 threshold and everything would be filtered
        mock_rerank = AsyncMock(return_value=[-2.0, -6.0])

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_BACKEND = "cross-encoder"
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_CHUNKS = 20
            mock_settings.RAG_RERANK_CROSS_ENCODER_MODEL = "test-ce-model"
            mock_settings.RAG_RERANK_SCORE_THRESHOLD = 0.01

            with patch("app.services.cross_encoder.rerank_async", mock_rerank):
                result = await rerank_rag_context(messages, "query")

        assert result is not None
        # chunk_a survives (sigmoid(-2) ≈ 0.12 > 0.01), chunk_b filtered (sigmoid(-6) ≈ 0.0025 < 0.01)
        assert result.kept_chunks == 1

    @pytest.mark.asyncio
    async def test_cross_encoder_all_negative_scores_keep_some(self):
        """Even with all-negative logits, sigmoid + low threshold keeps reasonably relevant chunks."""
        chunk_a = "A" * 2000
        chunk_b = "B" * 2000
        chunk_c = "C" * 2000
        messages = [
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk_a}{CHUNK_SEPARATOR}{chunk_b}{CHUNK_SEPARATOR}{chunk_c}"},
        ]

        # All negative logits: -1 → sigmoid ≈ 0.27, -3 → sigmoid ≈ 0.047, -4 → sigmoid ≈ 0.018
        # With threshold 0.01, all three survive (all sigmoid values > 0.01)
        mock_rerank = AsyncMock(return_value=[-1.0, -3.0, -4.0])

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_BACKEND = "cross-encoder"
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_CHUNKS = 20
            mock_settings.RAG_RERANK_CROSS_ENCODER_MODEL = "test-ce-model"
            mock_settings.RAG_RERANK_SCORE_THRESHOLD = 0.01

            with patch("app.services.cross_encoder.rerank_async", mock_rerank):
                result = await rerank_rag_context(messages, "query")

        assert result is not None
        assert result.kept_chunks == 3  # all survive with 0.01 threshold

    @pytest.mark.asyncio
    async def test_cross_encoder_score_threshold(self):
        """All chunks below threshold after sigmoid are filtered out."""
        chunk_a = "A" * 3000
        chunk_b = "B" * 3000
        messages = [
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk_a}{CHUNK_SEPARATOR}{chunk_b}"},
        ]

        # Very negative logits: -10 → sigmoid ≈ 0.00005, -12 → sigmoid ≈ 0.000006
        # Both well below threshold 0.01
        mock_rerank = AsyncMock(return_value=[-10.0, -12.0])

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_BACKEND = "cross-encoder"
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_CHUNKS = 20
            mock_settings.RAG_RERANK_CROSS_ENCODER_MODEL = "test-ce-model"
            mock_settings.RAG_RERANK_SCORE_THRESHOLD = 0.01

            with patch("app.services.cross_encoder.rerank_async", mock_rerank):
                result = await rerank_rag_context(messages, "query")

        assert result is not None
        assert result.kept_chunks == 0

    @pytest.mark.asyncio
    async def test_cross_encoder_max_chunks(self):
        """Max chunks limits how many chunks are kept even if all score above threshold."""
        chunk_a = "A" * 2000
        chunk_b = "B" * 2000
        chunk_c = "C" * 2000
        messages = [
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk_a}{CHUNK_SEPARATOR}{chunk_b}{CHUNK_SEPARATOR}{chunk_c}"},
        ]

        # All positive logits → sigmoid all > 0.5
        mock_rerank = AsyncMock(return_value=[2.0, 1.5, 1.0])

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_BACKEND = "cross-encoder"
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_CHUNKS = 2  # only keep 2
            mock_settings.RAG_RERANK_CROSS_ENCODER_MODEL = "test-ce-model"
            mock_settings.RAG_RERANK_SCORE_THRESHOLD = 0.01

            with patch("app.services.cross_encoder.rerank_async", mock_rerank):
                result = await rerank_rag_context(messages, "query")

        assert result is not None
        assert result.kept_chunks == 2

    @pytest.mark.asyncio
    async def test_cross_encoder_removes_empty_messages(self):
        """When all chunks in a message score below threshold, the message is removed."""
        chunk_a = "A" * 2000
        chunk_b = "B" * 2000
        chunk_c = "C" * 2000
        messages = [
            {"role": "system", "content": "Base prompt"},
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk_a}"},
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk_b}{CHUNK_SEPARATOR}{chunk_c}"},
            {"role": "user", "content": "hello"},
        ]

        # chunk_a scores high (logit 3 → sigmoid ≈ 0.95), chunk_b/c below threshold
        mock_rerank = AsyncMock(return_value=[3.0, -10.0, -12.0])

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_BACKEND = "cross-encoder"
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_CHUNKS = 20
            mock_settings.RAG_RERANK_CROSS_ENCODER_MODEL = "test-ce-model"
            mock_settings.RAG_RERANK_SCORE_THRESHOLD = 0.01

            with patch("app.services.cross_encoder.rerank_async", mock_rerank):
                result = await rerank_rag_context(messages, "query")

        assert result is not None
        assert result.kept_chunks == 1  # only chunk_a survives
        # knowledge message had both chunks removed — should be dropped
        assert len(messages) == 3  # base prompt, skill, user

    @pytest.mark.asyncio
    async def test_cross_encoder_content_verification(self):
        """Verify that surviving chunks have correct content in the mutated message."""
        chunk_a = "ALPHA" * 400
        chunk_b = "BRAVO" * 400
        chunk_c = "CHARLIE" * 400
        messages = [
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk_a}{CHUNK_SEPARATOR}{chunk_b}{CHUNK_SEPARATOR}{chunk_c}"},
        ]

        # Keep chunk_a and chunk_c (positive logits), remove chunk_b (very negative)
        mock_rerank = AsyncMock(return_value=[3.0, -10.0, 2.0])

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_BACKEND = "cross-encoder"
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_CHUNKS = 20
            mock_settings.RAG_RERANK_CROSS_ENCODER_MODEL = "test-ce-model"
            mock_settings.RAG_RERANK_SCORE_THRESHOLD = 0.01

            with patch("app.services.cross_encoder.rerank_async", mock_rerank):
                result = await rerank_rag_context(messages, "query")

        assert result is not None
        assert result.kept_chunks == 2
        content = messages[0]["content"]
        assert chunk_a in content
        assert chunk_b not in content
        assert chunk_c in content

    @pytest.mark.asyncio
    async def test_cross_encoder_failure_returns_none(self):
        chunk = "A" * 6000
        messages = [
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk}"},
        ]

        mock_rerank = AsyncMock(side_effect=Exception("ONNX crash"))

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_BACKEND = "cross-encoder"
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_CHUNKS = 20
            mock_settings.RAG_RERANK_CROSS_ENCODER_MODEL = "test-ce-model"
            mock_settings.RAG_RERANK_SCORE_THRESHOLD = 0.01

            with patch("app.services.cross_encoder.rerank_async", mock_rerank):
                result = await rerank_rag_context(messages, "query")

        assert result is None

    @pytest.mark.asyncio
    async def test_unknown_backend_returns_none(self):
        chunk = "A" * 6000
        messages = [
            {"role": "system", "content": f"Relevant knowledge:\n\n{chunk}"},
        ]

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_BACKEND = "bogus"
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_SCORE_THRESHOLD = 0.01
            result = await rerank_rag_context(messages, "query")

        assert result is None

    @pytest.mark.asyncio
    async def test_pinned_skills_excluded_from_cross_encoder(self):
        """Pinned skills should not be subject to cross-encoder reranking."""
        pinned_chunk = "PINNED" * 1000
        rag_chunk_a = "RAG_A" * 600
        rag_chunk_b = "RAG_B" * 600
        messages = [
            {"role": "system", "content": f"Pinned skill context:\n\n{pinned_chunk}"},
            {"role": "system", "content": f"Relevant knowledge:\n\n{rag_chunk_a}{CHUNK_SEPARATOR}{rag_chunk_b}"},
        ]

        # Only 2 RAG chunks should be scored (not the pinned one)
        # Logit 2 → sigmoid ≈ 0.88, logit -10 → sigmoid ≈ 0.00005
        mock_rerank = AsyncMock(return_value=[2.0, -10.0])

        with patch("app.services.reranking.settings") as mock_settings:
            mock_settings.RAG_RERANK_ENABLED = True
            mock_settings.RAG_RERANK_BACKEND = "cross-encoder"
            mock_settings.RAG_RERANK_THRESHOLD_CHARS = 100
            mock_settings.RAG_RERANK_MAX_CHUNKS = 20
            mock_settings.RAG_RERANK_CROSS_ENCODER_MODEL = "test-ce-model"
            mock_settings.RAG_RERANK_SCORE_THRESHOLD = 0.01

            with patch("app.services.cross_encoder.rerank_async", mock_rerank):
                result = await rerank_rag_context(messages, "query")

        assert result is not None
        assert result.original_chunks == 2  # only RAG chunks counted
        assert result.kept_chunks == 1  # only rag_chunk_a survives
        # Pinned message should still be present and untouched
        assert len(messages) == 2
        assert "PINNED" in messages[0]["content"]
        assert "RAG_A" in messages[1]["content"]
        assert "RAG_B" not in messages[1]["content"]
