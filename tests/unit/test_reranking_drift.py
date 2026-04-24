"""Phase N.5 — reranker header-prefix drift seams.

Covers contract edges between `app/agent/rag_formatting.py` (the shared RAG
header surface consumed by context assembly *and* the reranker) and
`app/services/reranking.py::_identify_rag_messages` + the rebuild path in
`rerank_rag_context`.

Drift seams pinned:
1. Prefix-order priority: ``_RAG_PREFIXES`` is iterated in declaration order.
   A message that could match both ``GENERIC_KNOWLEDGE_RAG_PREFIX`` ("Relevant
   knowledge") and ``CHANNEL_KNOWLEDGE_BASE_RAG_PREFIX`` (longer) is captured
   by whichever comes first, and both route to "knowledge" source — so the
   priority contract is *stable-by-accident* via same-source grouping.
2. Memory header with no double-newline silently drops (no crash, no chunks).
3. Empty body after a valid prefix yields zero chunks, message excluded.
4. Non-memory messages use the bare prefix constant (not a captured header
   slice) — important for reconstruction after rerank.
5. ``rerank_rag_context`` preserves the original prefix on each retained
   message after chunk filtering, and removes messages whose chunks were all
   dropped (reverse-index invariant).
6. Non-string system content (structured blocks, lists) is ignored without
   crash.
7. ``CONVERSATION_SECTIONS_RAG_PREFIX`` embeds the terminator in the prefix
   itself (ends with ``:\\n\\n``), so body-stripping is a no-op — pinned so a
   future refactor doesn't normalize the trailing newlines.
"""
from __future__ import annotations

import pytest

from app.agent.rag_formatting import (
    CHANNEL_INDEX_SEGMENTS_RAG_PREFIX,
    CHANNEL_KNOWLEDGE_BASE_RAG_PREFIX,
    CONVERSATION_SECTIONS_RAG_PREFIX,
    GENERIC_KNOWLEDGE_RAG_PREFIX,
    LEGACY_WORKSPACE_RAG_PREFIX,
    MEMORY_RAG_PREFIX,
    RERANKABLE_RAG_PREFIXES,
    WORKSPACE_RAG_PREFIX,
)
from app.services.reranking import (
    CHUNK_SEPARATOR,
    _identify_rag_messages,
    rerank_rag_context,
)


# ---------------------------------------------------------------------------
# _identify_rag_messages — edge cases beyond existing test_reranking.py
# ---------------------------------------------------------------------------


class TestPrefixOrderContract:
    def test_generic_knowledge_is_listed_before_channel_knowledge(self):
        """Priority: shorter 'Relevant knowledge' sits earlier than the longer
        channel-KB headers in RERANKABLE_RAG_PREFIXES. Both map to 'knowledge'
        source, which is why the loop terminates on either match without
        caller-visible drift. Pinning the ordering so a reshuffle that
        introduces a *different* source in front wouldn't silently reclassify
        incoming chunks.
        """
        prefixes = [p for p, _ in RERANKABLE_RAG_PREFIXES]
        sources = {p: s for p, s in RERANKABLE_RAG_PREFIXES}

        generic_idx = prefixes.index(GENERIC_KNOWLEDGE_RAG_PREFIX)
        channel_idx = prefixes.index(CHANNEL_KNOWLEDGE_BASE_RAG_PREFIX)
        index_idx = prefixes.index(CHANNEL_INDEX_SEGMENTS_RAG_PREFIX)

        assert generic_idx < channel_idx < index_idx
        assert sources[GENERIC_KNOWLEDGE_RAG_PREFIX] == "knowledge"
        assert sources[CHANNEL_KNOWLEDGE_BASE_RAG_PREFIX] == "knowledge"
        assert sources[CHANNEL_INDEX_SEGMENTS_RAG_PREFIX] == "knowledge"


class TestMemoryHeaderEdgeCases:
    def test_memory_without_double_newline_is_silently_dropped(self):
        """Memory path scans for the first ``\\n\\n`` to split header from
        body; a memory-prefixed message with no double-newline never surfaces
        as a rerankable block. Contract: silent-drop (no exception, no
        partial-include) so a mis-formatted injection doesn't get reranked
        against an empty body.
        """
        messages = [
            {
                "role": "system",
                "content": f"{MEMORY_RAG_PREFIX} inline with no header break",
            },
        ]

        result = _identify_rag_messages(messages)
        assert result == []

    def test_memory_with_empty_body_yields_no_chunks(self):
        messages = [
            {"role": "system", "content": f"{MEMORY_RAG_PREFIX}:\n\n"},
        ]

        result = _identify_rag_messages(messages)
        assert result == []


class TestNonMemoryPrefixEdgeCases:
    def test_non_memory_prefix_is_captured_as_bare_constant(self):
        """The reranker stores ``actual_prefix == prefix`` for non-memory
        matches — i.e. the bare constant from ``RERANKABLE_RAG_PREFIXES``.
        Rebuild after rerank uses that bare prefix + chunk joiner, so tests
        of the round-trip need to match the constant not a header slice.
        """
        body = "doc1\n\n---\n\ndoc2"
        messages = [
            {
                "role": "system",
                "content": f"{GENERIC_KNOWLEDGE_RAG_PREFIX}:\n\n{body}",
            },
        ]

        result = _identify_rag_messages(messages)

        assert len(result) == 1
        # Bare constant — NOT the header with ':\n\n' appended.
        assert result[0].prefix == GENERIC_KNOWLEDGE_RAG_PREFIX
        # Body kept intact including the leading ":\n\n"
        assert result[0].chunks[0].startswith(":")

    def test_empty_body_after_prefix_yields_zero_chunks(self):
        messages = [
            {"role": "system", "content": WORKSPACE_RAG_PREFIX},
        ]

        result = _identify_rag_messages(messages)
        assert result == []

    def test_non_string_system_content_is_ignored(self):
        """A system message with structured (non-string) content — e.g. a
        list of content parts — must not crash the prefix scan; it's simply
        skipped.
        """
        messages = [
            {"role": "system", "content": [{"type": "text", "text": "hi"}]},
            {"role": "system", "content": None},
            {"role": "system", "content": 42},
        ]

        result = _identify_rag_messages(messages)
        assert result == []

    def test_conversation_sections_prefix_embeds_header_terminator(self):
        """``CONVERSATION_SECTIONS_RAG_PREFIX`` is the only entry in the list
        whose constant *already ends* with ``:\\n\\n``. Pinning the shape so
        a refactor that strips trailing newlines from header constants
        doesn't silently change matching behavior for every caller.
        """
        assert CONVERSATION_SECTIONS_RAG_PREFIX.endswith(":\n\n")
        body = "section1\n\n---\n\nsection2"
        messages = [
            {
                "role": "system",
                "content": f"{CONVERSATION_SECTIONS_RAG_PREFIX}{body}",
            },
        ]

        result = _identify_rag_messages(messages)
        assert len(result) == 1
        assert result[0].source == "conversation_sections"
        assert len(result[0].chunks) == 2


# ---------------------------------------------------------------------------
# rerank_rag_context rebuild path — prefix preservation + reverse-index
# removal contract.
# ---------------------------------------------------------------------------


class TestRerankRebuildContract:
    @pytest.mark.asyncio
    async def test_rebuild_preserves_prefix_and_drops_fully_filtered_messages(
        self, monkeypatch
    ):
        """Force a deterministic keep_set via a stub cross-encoder: keep
        chunks [0, 2] out of 4 across two messages.

        Message layout (indices in ``messages``):
          0 — base system prompt (non-RAG, untouched)
          1 — knowledge RAG, two chunks (chunks 0, 1 globally)
          2 — filesystem RAG, two chunks (chunks 2, 3 globally)

        Expectation:
          - Message 1 keeps chunk 0 only; content = prefix + chunk0 (no joiner).
          - Message 2 keeps chunk 2 (local idx 0); content = prefix + chunk.
          - Message ordering preserved; non-RAG system prompt at index 0
            untouched.
        """
        from app.services import reranking as rr

        async def fake_cross_encoder(all_chunks, _user):
            # keep globals {0, 2}
            return {0, 2}

        monkeypatch.setattr(rr, "_rerank_via_cross_encoder", fake_cross_encoder)
        # Force backend + thresholds deterministic.
        monkeypatch.setattr(rr.settings, "RAG_RERANK_ENABLED", True, raising=False)
        monkeypatch.setattr(rr.settings, "RAG_RERANK_BACKEND", "cross-encoder", raising=False)
        monkeypatch.setattr(rr.settings, "RAG_RERANK_THRESHOLD_CHARS", 0, raising=False)

        messages: list[dict] = [
            {"role": "system", "content": "Base system prompt"},
            {
                "role": "system",
                "content": f"{GENERIC_KNOWLEDGE_RAG_PREFIX}:\n\nkA{CHUNK_SEPARATOR}kB",
            },
            {
                "role": "system",
                "content": f"{LEGACY_WORKSPACE_RAG_PREFIX}:\n\nfA{CHUNK_SEPARATOR}fB",
            },
            {"role": "user", "content": "query"},
        ]

        result = await rerank_rag_context(messages, "query")

        assert result is not None
        assert result.original_chunks == 4
        assert result.kept_chunks == 2
        # Non-RAG prompt untouched at the front.
        assert messages[0]["content"] == "Base system prompt"
        # Kept knowledge — bare prefix + kA (chunk 0 survives, chunk 1 dropped).
        kept_knowledge = messages[1]["content"]
        assert kept_knowledge == f"{GENERIC_KNOWLEDGE_RAG_PREFIX}:\n\nkA"
        # Kept filesystem — bare prefix + fA (chunk 0 [global 2] survives).
        kept_fs = messages[2]["content"]
        assert kept_fs == f"{LEGACY_WORKSPACE_RAG_PREFIX}:\n\nfA"
        # User message is after the two surviving RAG messages at index 3.
        assert messages[-1] == {"role": "user", "content": "query"}

    @pytest.mark.asyncio
    async def test_rebuild_drops_message_when_all_chunks_filtered(
        self, monkeypatch
    ):
        """When a RAG message's chunks are ALL filtered out, the message is
        removed from ``messages`` entirely (reverse-index pop) and its index
        surfaces in ``RerankResult.removed_message_indices``.
        """
        from app.services import reranking as rr

        async def fake_cross_encoder(all_chunks, _user):
            return set()  # keep nothing

        monkeypatch.setattr(rr, "_rerank_via_cross_encoder", fake_cross_encoder)
        monkeypatch.setattr(rr.settings, "RAG_RERANK_ENABLED", True, raising=False)
        monkeypatch.setattr(rr.settings, "RAG_RERANK_BACKEND", "cross-encoder", raising=False)
        monkeypatch.setattr(rr.settings, "RAG_RERANK_THRESHOLD_CHARS", 0, raising=False)

        messages: list[dict] = [
            {"role": "system", "content": "Base"},
            {
                "role": "system",
                "content": f"{GENERIC_KNOWLEDGE_RAG_PREFIX}:\n\nk1{CHUNK_SEPARATOR}k2",
            },
            {"role": "user", "content": "q"},
        ]

        result = await rerank_rag_context(messages, "q")

        assert result is not None
        assert result.kept_chunks == 0
        assert result.removed_message_indices == [1]
        # Knowledge message removed entirely.
        assert all(GENERIC_KNOWLEDGE_RAG_PREFIX not in (m.get("content") or "") for m in messages)
        assert messages[-1] == {"role": "user", "content": "q"}
