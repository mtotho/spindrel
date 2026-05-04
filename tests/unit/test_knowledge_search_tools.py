"""Unit tests for search_channel_knowledge + search_bot_knowledge tools."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


def _make_bot(shared_workspace_id=None):
    ws_indexing = SimpleNamespace(
        enabled=True,
        patterns=["**/*.md"],
        similarity_threshold=0.3,
        top_k=10,
        watch=False,
        cooldown_seconds=60,
        embedding_model=None,
        segments=[],
    )
    ws = SimpleNamespace(enabled=True, indexing=ws_indexing)
    return SimpleNamespace(
        id="bot-1",
        shared_workspace_id=shared_workspace_id,
        workspace=ws,
        _workspace_raw={"indexing": {}},
        _ws_indexing_config=None,
        cross_workspace_access=False,
    )


class _FakeResult:
    def __init__(self, file_path, content, score=0.8):
        self.file_path = file_path
        self.content = content
        self.score = score


# ---------------------------------------------------------------------------
# search_workspace
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_workspace_excludes_user_knowledge_prefix():
    """Generic workspace search must not expose user-scope Knowledge Documents."""
    from app.agent.context import current_bot_id
    from app.tools.local.workspace import search_workspace

    bot = _make_bot(shared_workspace_id="ws-1")
    retrieve_mock = AsyncMock(return_value=([], 0.0))

    tok = current_bot_id.set("bot-1")
    try:
        with patch("app.agent.bots.get_bot", return_value=bot), \
             patch("app.services.bot_indexing.resolve_for", return_value=SimpleNamespace(
                 roots=["/data/shared/ws-1"],
                 top_k=10,
                 similarity_threshold=0.3,
                 embedding_model="text-embedding-3-small",
                 segments=[],
             )), \
             patch("app.agent.fs_indexer.retrieve_filesystem_context", new=retrieve_mock):
            await search_workspace("preferences")
    finally:
        current_bot_id.reset(tok)

    retrieve_mock.assert_awaited_once()
    assert retrieve_mock.call_args.kwargs["exclude_path_prefixes"] == ["users"]


# ---------------------------------------------------------------------------
# search_channel_knowledge
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_channel_knowledge_scopes_to_kb_prefix():
    """The tool passes channels/{id}/knowledge-base as the memory prefix."""
    from app.tools.local.channel_workspace import search_channel_knowledge
    from app.agent.context import current_bot_id, current_channel_id

    bot = _make_bot(shared_workspace_id="ws-1")
    hybrid_mock = AsyncMock(return_value=[_FakeResult(
        "channels/ch-7/knowledge-base/oranges.md", "# Oranges\nCitrus fact"
    )])

    tok_b = current_bot_id.set("bot-1")
    tok_c = current_channel_id.set("ch-7")
    try:
        with patch(
            "app.tools.local.channel_workspace._get_bot_and_roots",
            new=AsyncMock(return_value=(bot, "ch-7", "/ws", "text-embedding-3-small", None, None)),
        ), patch("app.services.memory_search.hybrid_memory_search", new=hybrid_mock):
            result = await search_channel_knowledge("what about oranges?")
    finally:
        current_bot_id.reset(tok_b)
        current_channel_id.reset(tok_c)

    hybrid_mock.assert_awaited_once()
    call = hybrid_mock.call_args
    assert call.kwargs["memory_prefix"] == "channels/ch-7/knowledge-base"
    assert call.kwargs["bot_id"] == "channel:ch-7"
    assert "Citrus fact" in result


@pytest.mark.asyncio
async def test_search_channel_knowledge_empty_query():
    """Empty query returns a friendly message without calling the search."""
    from app.tools.local.channel_workspace import search_channel_knowledge
    from app.agent.context import current_bot_id, current_channel_id

    bot = _make_bot()
    tok_b = current_bot_id.set("bot-1")
    tok_c = current_channel_id.set("ch-7")
    try:
        with patch(
            "app.tools.local.channel_workspace._get_bot_and_roots",
            new=AsyncMock(return_value=(bot, "ch-7", "/ws", "text-embedding-3-small", None, None)),
        ):
            out = await search_channel_knowledge("   ")
    finally:
        current_bot_id.reset(tok_b)
        current_channel_id.reset(tok_c)

    assert "No search query" in out


@pytest.mark.asyncio
async def test_search_channel_knowledge_no_context_returns_message():
    """Without bot + channel context the tool returns a friendly availability message."""
    from app.tools.local.channel_workspace import search_channel_knowledge
    # No context set → current_bot_id.get() returns None
    out = await search_channel_knowledge("anything")
    assert "not available" in out.lower()


# ---------------------------------------------------------------------------
# search_bot_knowledge
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_bot_knowledge_standalone_prefix():
    """Standalone bot uses prefix 'knowledge-base' (no bots/ segment)."""
    from app.tools.local.workspace import search_bot_knowledge
    from app.agent.context import current_bot_id

    bot = _make_bot(shared_workspace_id=None)
    hybrid_mock = AsyncMock(return_value=[_FakeResult(
        "knowledge-base/family.md", "# Family\nGrandma's recipe"
    )])

    tok = current_bot_id.set("bot-1")
    try:
        with patch("app.agent.bots.get_bot", return_value=bot), \
             patch("app.services.workspace_indexing.resolve_indexing", return_value={
                 "embedding_model": "text-embedding-3-small", "top_k": 10,
                 "similarity_threshold": 0.3, "patterns": ["**/*.md"], "watch": False,
                 "cooldown_seconds": 60, "include_bots": [], "segments": [],
                 "segments_source": "default",
             }), \
             patch("app.services.workspace_indexing.get_all_roots", return_value=["/data/bot-1"]), \
             patch("app.services.memory_search.hybrid_memory_search", new=hybrid_mock):
            result = await search_bot_knowledge("grandma")
    finally:
        current_bot_id.reset(tok)

    call = hybrid_mock.call_args
    assert call.kwargs["memory_prefix"] == "knowledge-base"
    assert call.kwargs["bot_id"] == "bot-1"
    assert "Grandma's recipe" in result


@pytest.mark.asyncio
async def test_search_bot_knowledge_shared_workspace_prefix():
    """Shared-workspace bot stores KB under bots/<id>/knowledge-base/."""
    from app.tools.local.workspace import search_bot_knowledge
    from app.agent.context import current_bot_id

    bot = _make_bot(shared_workspace_id="ws-1")
    hybrid_mock = AsyncMock(return_value=[])

    tok = current_bot_id.set("bot-1")
    try:
        with patch("app.agent.bots.get_bot", return_value=bot), \
             patch("app.services.workspace_indexing.resolve_indexing", return_value={
                 "embedding_model": "text-embedding-3-small", "top_k": 10,
                 "similarity_threshold": 0.3, "patterns": ["**/*.md"], "watch": False,
                 "cooldown_seconds": 60, "include_bots": [], "segments": [],
                 "segments_source": "default",
             }), \
             patch("app.services.workspace_indexing.get_all_roots", return_value=["/data/shared/ws-1"]), \
             patch("app.services.memory_search.hybrid_memory_search", new=hybrid_mock):
            result = await search_bot_knowledge("anything")
    finally:
        current_bot_id.reset(tok)

    call = hybrid_mock.call_args
    assert call.kwargs["memory_prefix"] == "bots/bot-1/knowledge-base"
    assert "No matching" in result


@pytest.mark.asyncio
async def test_search_bot_knowledge_no_bot_context():
    """No current_bot_id → explicit error response (no bot registry crash)."""
    from app.tools.local.workspace import search_bot_knowledge
    out = await search_bot_knowledge("anything")
    # Falls through to JSON error or workspace-disabled message
    assert "bot context" in out.lower() or "not available" in out.lower()
