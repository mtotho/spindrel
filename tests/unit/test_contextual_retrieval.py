"""Tests for app.agent.contextual_retrieval — LLM-generated chunk descriptions."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent import contextual_retrieval as cr


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset in-memory cache between tests."""
    cr._context_cache.clear()
    yield
    cr._context_cache.clear()


def _mock_settings(**overrides):
    s = MagicMock()
    defaults = dict(
        CONTEXTUAL_RETRIEVAL_ENABLED=True,
        CONTEXTUAL_RETRIEVAL_MODEL="gpt-4o-mini",
        CONTEXTUAL_RETRIEVAL_MAX_TOKENS=150,
        CONTEXTUAL_RETRIEVAL_BATCH_SIZE=5,
        CONTEXTUAL_RETRIEVAL_PROVIDER_ID="",
        COMPACTION_MODEL="gpt-4o-mini",
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _mock_llm_response(content: str):
    """Build a minimal chat completion response."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ---------------------------------------------------------------------------
# generate_chunk_context
# ---------------------------------------------------------------------------

class TestGenerateChunkContext:
    async def test_returns_none_when_disabled(self):
        with patch.object(cr, "settings", _mock_settings(CONTEXTUAL_RETRIEVAL_ENABLED=False)):
            result = await cr.generate_chunk_context("chunk", "doc", "title", 0, "hash123")
        assert result is None

    async def test_returns_description_on_success(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response("This chunk describes the main architecture.")
        )
        with patch.object(cr, "settings", _mock_settings()), \
             patch("app.services.providers.get_llm_client", return_value=mock_client):
            result = await cr.generate_chunk_context("chunk text", "full doc", "My Doc", 0, "abc")
        assert result == "This chunk describes the main architecture."

    async def test_caches_result(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response("cached description")
        )
        with patch.object(cr, "settings", _mock_settings()), \
             patch("app.services.providers.get_llm_client", return_value=mock_client):
            r1 = await cr.generate_chunk_context("chunk", "doc", "title", 0, "hash1")
            r2 = await cr.generate_chunk_context("chunk", "doc", "title", 0, "hash1")
        assert r1 == r2 == "cached description"
        # Only one LLM call despite two invocations
        assert mock_client.chat.completions.create.await_count == 1

    async def test_returns_none_on_llm_failure(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("LLM down"))
        with patch.object(cr, "settings", _mock_settings()), \
             patch("app.services.providers.get_llm_client", return_value=mock_client):
            result = await cr.generate_chunk_context("chunk", "doc", "title", 0, "hash2")
        assert result is None

    async def test_returns_none_when_no_model(self):
        with patch.object(cr, "settings", _mock_settings(
            CONTEXTUAL_RETRIEVAL_MODEL="", COMPACTION_MODEL=""
        )):
            result = await cr.generate_chunk_context("chunk", "doc", "title", 0, "hash3")
        assert result is None

    async def test_uses_compaction_model_as_fallback(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response("ok")
        )
        with patch.object(cr, "settings", _mock_settings(
            CONTEXTUAL_RETRIEVAL_MODEL="", COMPACTION_MODEL="gpt-4o-mini"
        )), \
             patch("app.services.providers.get_llm_client", return_value=mock_client):
            await cr.generate_chunk_context("chunk", "doc", "title", 0, "hash4")
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o-mini"

    async def test_returns_none_on_whitespace_only_content(self):
        """LLM returns whitespace-only → strips to empty → returns None."""
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response("   \n  ")
        )
        with patch.object(cr, "settings", _mock_settings()), \
             patch("app.services.providers.get_llm_client", return_value=mock_client):
            result = await cr.generate_chunk_context("chunk", "doc", "title", 0, "hashWS")
        assert result is None

    async def test_returns_none_on_empty_choices(self):
        """Empty choices list → returns None gracefully."""
        mock_client = MagicMock()
        resp = MagicMock()
        resp.choices = []
        mock_client.chat.completions.create = AsyncMock(return_value=resp)
        with patch.object(cr, "settings", _mock_settings()), \
             patch("app.services.providers.get_llm_client", return_value=mock_client):
            result = await cr.generate_chunk_context("chunk", "doc", "title", 0, "hashE")
        assert result is None

    async def test_returns_none_on_none_content(self):
        """choices[0].message.content is None → returns None."""
        mock_client = MagicMock()
        msg = MagicMock()
        msg.content = None
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        mock_client.chat.completions.create = AsyncMock(return_value=resp)
        with patch.object(cr, "settings", _mock_settings()), \
             patch("app.services.providers.get_llm_client", return_value=mock_client):
            result = await cr.generate_chunk_context("chunk", "doc", "title", 0, "hashF")
        assert result is None

    async def test_lru_eviction_at_max_cache_size(self):
        """Cache evicts oldest entries when exceeding _MAX_CACHE_SIZE."""
        old_max = cr._MAX_CACHE_SIZE
        cr._MAX_CACHE_SIZE = 3
        try:
            mock_client = MagicMock()
            call_idx = {"n": 0}

            async def _create(**kwargs):
                call_idx["n"] += 1
                return _mock_llm_response(f"desc {call_idx['n']}")

            mock_client.chat.completions.create = AsyncMock(side_effect=_create)
            with patch.object(cr, "settings", _mock_settings()), \
                 patch("app.services.providers.get_llm_client", return_value=mock_client):
                for i in range(5):
                    await cr.generate_chunk_context("c", "doc", "t", i, "hashG")
            # Cache should have at most 3 entries
            assert len(cr._context_cache) == 3
            # Oldest entries (index 0, 1) should be evicted
            assert ("hashG", 0) not in cr._context_cache
            assert ("hashG", 1) not in cr._context_cache
            # Newest entries should remain
            assert ("hashG", 4) in cr._context_cache
        finally:
            cr._MAX_CACHE_SIZE = old_max

    async def test_truncates_long_documents(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_llm_response("ok")
        )
        long_doc = "x" * 10000
        with patch.object(cr, "settings", _mock_settings()), \
             patch("app.services.providers.get_llm_client", return_value=mock_client):
            await cr.generate_chunk_context("chunk", long_doc, "title", 0, "hash5")
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        prompt = call_kwargs["messages"][0]["content"]
        assert "truncated" in prompt


# ---------------------------------------------------------------------------
# generate_batch_contexts
# ---------------------------------------------------------------------------

class TestGenerateBatchContexts:
    async def test_returns_none_list_when_disabled(self):
        chunks = [{"text": "a", "index": 0}, {"text": "b", "index": 1}]
        with patch.object(cr, "settings", _mock_settings(CONTEXTUAL_RETRIEVAL_ENABLED=False)):
            result = await cr.generate_batch_contexts(chunks, "doc", "title", "hash")
        assert result == [None, None]

    async def test_processes_all_chunks(self):
        mock_client = MagicMock()
        call_count = {"n": 0}

        async def _create(**kwargs):
            call_count["n"] += 1
            return _mock_llm_response(f"desc {call_count['n']}")

        mock_client.chat.completions.create = AsyncMock(side_effect=_create)
        chunks = [{"text": f"chunk {i}", "index": i} for i in range(3)]
        with patch.object(cr, "settings", _mock_settings()), \
             patch("app.services.providers.get_llm_client", return_value=mock_client):
            result = await cr.generate_batch_contexts(chunks, "doc", "title", "hashB")
        assert len(result) == 3
        assert all(d is not None for d in result)

    async def test_respects_batch_size_concurrency(self):
        """Semaphore limits concurrent LLM calls."""
        concurrent = {"current": 0, "max": 0}

        async def _create(**kwargs):
            import asyncio
            concurrent["current"] += 1
            concurrent["max"] = max(concurrent["max"], concurrent["current"])
            await asyncio.sleep(0.01)
            concurrent["current"] -= 1
            return _mock_llm_response("ok")

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=_create)
        chunks = [{"text": f"c{i}", "index": i} for i in range(10)]
        with patch.object(cr, "settings", _mock_settings(CONTEXTUAL_RETRIEVAL_BATCH_SIZE=2)), \
             patch("app.services.providers.get_llm_client", return_value=mock_client):
            await cr.generate_batch_contexts(chunks, "doc", "title", "hashC")
        assert concurrent["max"] <= 2


# ---------------------------------------------------------------------------
# build_embed_text
# ---------------------------------------------------------------------------

class TestBuildEmbedText:
    def test_all_parts(self):
        result = cr.build_embed_text("content", "# Prefix", "LLM description", "[Skill]")
        assert result == "# Prefix\n\nLLM description\n\ncontent"

    def test_no_description(self):
        result = cr.build_embed_text("content", "# Prefix", None, "[Skill]")
        assert result == "# Prefix\n\ncontent"

    def test_no_prefix_uses_source_label(self):
        result = cr.build_embed_text("content", None, "desc", "[Skill: X]")
        assert result == "[Skill: X]\n\ndesc\n\ncontent"

    def test_no_prefix_no_label(self):
        result = cr.build_embed_text("content", None, "desc", None)
        assert result == "desc\n\ncontent"

    def test_content_only(self):
        result = cr.build_embed_text("just content")
        assert result == "just content"

    def test_empty_prefix_and_label_not_prepended(self):
        """Empty strings (truthy check) should not produce extra blank lines."""
        result = cr.build_embed_text("content", context_prefix="", contextual_description="", source_label="")
        assert result == "content"


# ---------------------------------------------------------------------------
# warm_cache_from_metadata
# ---------------------------------------------------------------------------

class TestWarmCache:
    def test_loads_entries(self):
        rows = [
            ("hash1", 0, "desc A"),
            ("hash1", 1, "desc B"),
            ("hash2", 0, None),  # no description
        ]
        loaded = cr.warm_cache_from_metadata(rows)
        assert loaded == 2
        assert cr._context_cache[("hash1", 0)] == "desc A"
        assert ("hash2", 0) not in cr._context_cache


# ---------------------------------------------------------------------------
# get_effective_chunking_version
# ---------------------------------------------------------------------------

class TestEffectiveChunkingVersion:
    def test_adds_cr_suffix_when_enabled(self):
        with patch.object(cr, "settings", _mock_settings(CONTEXTUAL_RETRIEVAL_ENABLED=True)):
            assert cr.get_effective_chunking_version("v3") == "v3+cr"

    def test_no_suffix_when_disabled(self):
        with patch.object(cr, "settings", _mock_settings(CONTEXTUAL_RETRIEVAL_ENABLED=False)):
            assert cr.get_effective_chunking_version("v3") == "v3"
