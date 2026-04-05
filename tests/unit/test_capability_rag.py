"""Unit tests for capability RAG (embedding/retrieval of capabilities)."""
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Mock carapace registry data
# ---------------------------------------------------------------------------

_MOCK_REGISTRY = {
    "code-review": {
        "id": "code-review",
        "name": "Code Review",
        "description": "PR analysis, best practices, security checks",
        "system_prompt_fragment": "You are a code review expert. Focus on correctness, security.",
        "skills": [{"id": "code-review-checklist", "mode": "pinned"}],
        "local_tools": ["exec_command"],
        "mcp_tools": [],
        "pinned_tools": [],
        "includes": [],
        "tags": ["development", "review"],
        "source_type": "file",
    },
    "data-analyst": {
        "id": "data-analyst",
        "name": "Data Analyst",
        "description": "SQL, visualization, statistical methods",
        "system_prompt_fragment": "You are a data analyst.",
        "skills": [],
        "local_tools": ["web_search"],
        "mcp_tools": [],
        "pinned_tools": [],
        "includes": [],
        "tags": ["analysis"],
        "source_type": "manual",
    },
    "bug-fix": {
        "id": "bug-fix",
        "name": "Bug Fixer",
        "description": "Debugging, root cause analysis, fix verification",
        "system_prompt_fragment": "",
        "skills": ["bug-fix-checklist"],
        "local_tools": [],
        "mcp_tools": [],
        "pinned_tools": [],
        "includes": [],
        "tags": ["development"],
        "source_type": "file",
    },
}


def _mock_session_ctx(mock_db):
    """Create a mock async context manager that yields mock_db."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _mock_distance_expr():
    """Create a mock that behaves like a SQLAlchemy column expression."""
    from sqlalchemy import literal_column
    return literal_column("0")


# ---------------------------------------------------------------------------
# build_embed_text
# ---------------------------------------------------------------------------


class TestBuildEmbedText:
    def test_basic_output(self):
        from app.agent.capability_rag import build_embed_text

        text = build_embed_text(_MOCK_REGISTRY["code-review"])
        assert "Capability: Code Review" in text
        assert "Description: PR analysis" in text
        assert "Expertise: You are a code review expert" in text
        assert "Skills: code-review-checklist" in text
        assert "Tags: development, review" in text
        assert "Tools: exec_command" in text

    def test_minimal_carapace(self):
        from app.agent.capability_rag import build_embed_text

        cap = {"id": "minimal", "name": "Minimal"}
        text = build_embed_text(cap)
        assert "Capability: Minimal" in text
        assert "Description:" not in text
        assert "Skills:" not in text

    def test_string_skills(self):
        from app.agent.capability_rag import build_embed_text

        text = build_embed_text(_MOCK_REGISTRY["bug-fix"])
        assert "Skills: bug-fix-checklist" in text

    def test_fragment_truncation(self):
        from app.agent.capability_rag import build_embed_text

        cap = {
            "id": "long-frag",
            "name": "Long Fragment",
            "system_prompt_fragment": "x" * 1000,
        }
        text = build_embed_text(cap)
        # Should truncate to 500 chars
        expertise_line = [l for l in text.split("\n") if l.startswith("Expertise:")][0]
        assert len(expertise_line) == len("Expertise: ") + 500


# ---------------------------------------------------------------------------
# content_hash
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_deterministic(self):
        from app.agent.capability_rag import content_hash

        h1 = content_hash("hello world")
        h2 = content_hash("hello world")
        assert h1 == h2
        assert h1 == hashlib.sha256(b"hello world").hexdigest()

    def test_different_inputs(self):
        from app.agent.capability_rag import content_hash

        assert content_hash("a") != content_hash("b")


# ---------------------------------------------------------------------------
# index_capabilities — mock DB + embedding
# ---------------------------------------------------------------------------


class TestIndexCapabilities:
    @pytest.mark.asyncio
    async def test_indexes_all_capabilities(self):
        """index_capabilities should embed and upsert all registry entries."""
        from app.agent.capability_rag import index_capabilities

        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        with patch("app.agent.carapaces.list_carapaces", return_value=list(_MOCK_REGISTRY.values())), \
             patch("app.agent.capability_rag._embed_query", mock_embed), \
             patch("app.agent.capability_rag.async_session", return_value=_mock_session_ctx(mock_db)):
            await index_capabilities()

        assert mock_embed.call_count == len(_MOCK_REGISTRY)

    @pytest.mark.asyncio
    async def test_skips_unchanged(self):
        """Capabilities with matching content_hash should not be re-embedded."""
        from app.agent.capability_rag import index_capabilities, build_embed_text, content_hash

        cr_text = build_embed_text(_MOCK_REGISTRY["code-review"])
        cr_hash = content_hash(cr_text)

        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        mock_existing_row = MagicMock()
        mock_existing_row.carapace_id = "code-review"
        mock_existing_row.content_hash = cr_hash

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [mock_existing_row]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        with patch("app.agent.carapaces.list_carapaces", return_value=list(_MOCK_REGISTRY.values())), \
             patch("app.agent.capability_rag._embed_query", mock_embed), \
             patch("app.agent.capability_rag.async_session", return_value=_mock_session_ctx(mock_db)):
            await index_capabilities()

        # code-review skipped, other 2 embedded
        assert mock_embed.call_count == 2

    @pytest.mark.asyncio
    async def test_removes_stale(self):
        """Capabilities no longer in registry should be deleted from the index."""
        from app.agent.capability_rag import index_capabilities

        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        mock_stale_row = MagicMock()
        mock_stale_row.carapace_id = "deleted-cap"
        mock_stale_row.content_hash = "old-hash"

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [mock_stale_row]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        with patch("app.agent.carapaces.list_carapaces", return_value=list(_MOCK_REGISTRY.values())), \
             patch("app.agent.capability_rag._embed_query", mock_embed), \
             patch("app.agent.capability_rag.async_session", return_value=_mock_session_ctx(mock_db)):
            await index_capabilities()

        # At least the stale delete + hash fetch + upserts
        assert mock_db.execute.call_count >= 2


# ---------------------------------------------------------------------------
# reindex_capability
# ---------------------------------------------------------------------------


class TestReindexCapability:
    @pytest.mark.asyncio
    async def test_reindex_existing(self):
        """reindex_capability should embed and upsert a single capability."""
        from app.agent.capability_rag import reindex_capability

        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch("app.agent.carapaces.get_carapace", return_value=_MOCK_REGISTRY["code-review"]), \
             patch("app.agent.capability_rag._embed_query", mock_embed), \
             patch("app.agent.capability_rag.async_session", return_value=_mock_session_ctx(mock_db)):
            await reindex_capability("code-review")

        mock_embed.assert_called_once()

    @pytest.mark.asyncio
    async def test_reindex_deleted_capability(self):
        """reindex_capability for a deleted capability should remove the row."""
        from app.agent.capability_rag import reindex_capability

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        with patch("app.agent.carapaces.get_carapace", return_value=None), \
             patch("app.agent.capability_rag.async_session", return_value=_mock_session_ctx(mock_db)):
            await reindex_capability("deleted-cap")

        mock_db.execute.assert_called_once()


# ---------------------------------------------------------------------------
# retrieve_capabilities
# ---------------------------------------------------------------------------


class TestRetrieveCapabilities:
    @pytest.mark.asyncio
    async def test_retrieve_returns_results(self):
        """retrieve_capabilities should return matching capabilities above threshold."""
        from app.agent.capability_rag import retrieve_capabilities

        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        mock_row_1 = MagicMock()
        mock_row_1.carapace_id = "code-review"
        mock_row_1.name = "Code Review"
        mock_row_1.distance = 0.3  # similarity = 0.7

        mock_row_2 = MagicMock()
        mock_row_2.carapace_id = "data-analyst"
        mock_row_2.name = "Data Analyst"
        mock_row_2.distance = 0.6  # similarity = 0.4 — below 0.5 threshold

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row_1, mock_row_2]
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.agent.capability_rag._embed_query", mock_embed), \
             patch("app.agent.capability_rag.async_session", return_value=_mock_session_ctx(mock_db)), \
             patch("app.agent.carapaces.get_carapace", side_effect=lambda cid: _MOCK_REGISTRY.get(cid)), \
             patch("app.agent.vector_ops.halfvec_cosine_distance", return_value=_mock_distance_expr()):
            results, best_sim = await retrieve_capabilities(
                "review my pull request", threshold=0.50,
            )

        assert len(results) == 1
        assert results[0]["id"] == "code-review"
        assert results[0]["name"] == "Code Review"
        assert best_sim == 0.7

    @pytest.mark.asyncio
    async def test_retrieve_excludes_ids(self):
        """retrieve_capabilities should skip excluded IDs."""
        from app.agent.capability_rag import retrieve_capabilities

        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        mock_row = MagicMock()
        mock_row.carapace_id = "code-review"
        mock_row.name = "Code Review"
        mock_row.distance = 0.3

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.agent.capability_rag._embed_query", mock_embed), \
             patch("app.agent.capability_rag.async_session", return_value=_mock_session_ctx(mock_db)), \
             patch("app.agent.carapaces.get_carapace", side_effect=lambda cid: _MOCK_REGISTRY.get(cid)), \
             patch("app.agent.vector_ops.halfvec_cosine_distance", return_value=_mock_distance_expr()):
            results, best_sim = await retrieve_capabilities(
                "review my code",
                excluded_ids={"code-review"},
                threshold=0.50,
            )

        assert len(results) == 0
        assert best_sim == 0.0

    @pytest.mark.asyncio
    async def test_retrieve_respects_top_k(self):
        """retrieve_capabilities should return at most top_k results."""
        from app.agent.capability_rag import retrieve_capabilities

        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        mock_rows = []
        for i, cid in enumerate(["code-review", "data-analyst", "bug-fix"]):
            row = MagicMock()
            row.carapace_id = cid
            row.name = _MOCK_REGISTRY[cid]["name"]
            row.distance = 0.2 + (i * 0.05)
            mock_rows.append(row)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = mock_rows
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.agent.capability_rag._embed_query", mock_embed), \
             patch("app.agent.capability_rag.async_session", return_value=_mock_session_ctx(mock_db)), \
             patch("app.agent.carapaces.get_carapace", side_effect=lambda cid: _MOCK_REGISTRY.get(cid)), \
             patch("app.agent.vector_ops.halfvec_cosine_distance", return_value=_mock_distance_expr()):
            results, _ = await retrieve_capabilities(
                "help me debug", top_k=2, threshold=0.50,
            )

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_retrieve_handles_embed_failure(self):
        """retrieve_capabilities should return empty on embedding failure."""
        from app.agent.capability_rag import retrieve_capabilities

        mock_embed = AsyncMock(side_effect=Exception("API error"))

        with patch("app.agent.capability_rag._embed_query", mock_embed):
            results, best_sim = await retrieve_capabilities("some query")

        assert results == []
        assert best_sim == 0.0

    @pytest.mark.asyncio
    async def test_retrieve_empty_when_no_index(self):
        """retrieve_capabilities returns empty when DB has no rows."""
        from app.agent.capability_rag import retrieve_capabilities

        mock_embed = AsyncMock(return_value=[0.1] * 1536)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.agent.capability_rag._embed_query", mock_embed), \
             patch("app.agent.capability_rag.async_session", return_value=_mock_session_ctx(mock_db)), \
             patch("app.agent.vector_ops.halfvec_cosine_distance", return_value=_mock_distance_expr()):
            results, best_sim = await retrieve_capabilities("any query", threshold=0.50)

        assert results == []
        assert best_sim == 0.0
