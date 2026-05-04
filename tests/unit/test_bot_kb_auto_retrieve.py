"""Tests for implicit bot knowledge-base retrieval in context_assembly."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.context_assembly import AssemblyLedger, _inject_bot_knowledge_base, _inject_user_knowledge, _inject_workspace_rag


def _make_bot(*, shared_workspace_id: str | None = None, auto_retrieval: bool = True):
    ws_indexing = SimpleNamespace(
        enabled=True,
        patterns=["**/*.md"],
        similarity_threshold=0.3,
        top_k=8,
        watch=False,
        cooldown_seconds=60,
        embedding_model=None,
        segments=[],
    )
    ws = SimpleNamespace(
        enabled=True,
        indexing=ws_indexing,
        bot_knowledge_auto_retrieval=auto_retrieval,
    )
    return SimpleNamespace(
        id="bot-1",
        shared_workspace_id=shared_workspace_id,
        workspace=ws,
        _workspace_raw={"indexing": {}},
        _ws_indexing_config=None,
        local_tools=["search_bot_knowledge"],
        user_id="user-1",
    )


async def _collect(gen):
    return [e async for e in gen]


@pytest.mark.asyncio
async def test_bot_kb_auto_retrieval_uses_implicit_kb_segment():
    bot = _make_bot(shared_workspace_id="ws-1")
    messages: list[dict] = []
    ledger = AssemblyLedger()
    retrieve_mock = AsyncMock(return_value=(["[File: bots/bot-1/knowledge-base/facts.md]\n\nImportant fact"], 0.82))

    with patch("app.agent.fs_indexer.retrieve_filesystem_context", new=retrieve_mock), \
         patch("app.services.workspace_indexing.resolve_indexing", return_value={
             "embedding_model": "text-embedding-3-small",
             "patterns": ["**/*.md"],
             "similarity_threshold": 0.3,
             "top_k": 8,
             "watch": False,
             "cooldown_seconds": 60,
             "include_bots": [],
             "segments": [],
             "segments_source": "default",
         }), \
         patch("app.services.workspace_indexing.get_all_roots", return_value=["/data/shared/ws-1"]):
        events = await _collect(_inject_bot_knowledge_base(
            messages,
            bot,
            "what do you know about deployment?",
            ledger,
            context_profile=SimpleNamespace(allow_bot_knowledge_base=True),
        ))

    retrieve_mock.assert_called_once()
    call = retrieve_mock.call_args
    assert call.kwargs["segments"] == [{
        "path_prefix": "bots/bot-1/knowledge-base",
        "embedding_model": "text-embedding-3-small",
    }]
    assert call.kwargs["include_path_prefixes"] == ["bots/bot-1/knowledge-base"]
    assert any("search_bot_knowledge" in m["content"] for m in messages)
    assert ledger.inject_chars["bot_knowledge_base"] > 0
    assert events == [{"type": "bot_knowledge_base", "count": 1, "similarity": 0.82}]


@pytest.mark.asyncio
async def test_bot_kb_auto_retrieval_respects_toggle_off():
    bot = _make_bot(auto_retrieval=False)
    ledger = AssemblyLedger()

    with patch("app.agent.fs_indexer.retrieve_filesystem_context", new=AsyncMock()) as retrieve_mock:
        events = await _collect(_inject_bot_knowledge_base(
            [],
            bot,
            "query",
            ledger,
            context_profile=SimpleNamespace(allow_bot_knowledge_base=True),
        ))

    retrieve_mock.assert_not_called()
    assert events == []
    assert ledger.inject_decisions["bot_knowledge_base"] == "skipped_disabled"


@pytest.mark.asyncio
async def test_bot_kb_auto_retrieval_skips_when_budget_rejects():
    bot = _make_bot()
    messages: list[dict] = []
    ledger = AssemblyLedger()
    ledger.can_afford = lambda _: False

    with patch("app.agent.fs_indexer.retrieve_filesystem_context", new=AsyncMock(return_value=(
        ["[File: knowledge-base/facts.md]\n\nImportant fact"],
        0.71,
    ))), \
         patch("app.services.workspace_indexing.resolve_indexing", return_value={
             "embedding_model": "text-embedding-3-small",
             "patterns": ["**/*.md"],
             "similarity_threshold": 0.3,
             "top_k": 8,
             "watch": False,
             "cooldown_seconds": 60,
             "include_bots": [],
             "segments": [],
             "segments_source": "default",
         }), \
         patch("app.services.workspace_indexing.get_all_roots", return_value=["/data/bot-1"]):
        events = await _collect(_inject_bot_knowledge_base(
            messages,
            bot,
            "query",
            ledger,
            context_profile=SimpleNamespace(allow_bot_knowledge_base=True),
        ))

    assert events == []
    assert messages == []
    assert ledger.inject_decisions["bot_knowledge_base"] == "skipped_by_budget"


@pytest.mark.asyncio
async def test_bot_kb_auto_retrieval_respects_profile_gate():
    bot = _make_bot(auto_retrieval=True)
    ledger = AssemblyLedger()

    with patch("app.agent.fs_indexer.retrieve_filesystem_context", new=AsyncMock()) as retrieve_mock:
        events = await _collect(_inject_bot_knowledge_base(
            [],
            bot,
            "query",
            ledger,
            context_profile=SimpleNamespace(allow_bot_knowledge_base=False),
        ))

    retrieve_mock.assert_not_called()
    assert events == []
    assert ledger.inject_decisions["bot_knowledge_base"] == "skipped_by_profile"


@pytest.mark.asyncio
async def test_workspace_rag_excludes_dedicated_channel_and_bot_kb_chunks():
    bot = _make_bot(shared_workspace_id="ws-1")
    messages: list[dict] = []
    ledger = AssemblyLedger()
    retrieve_mock = AsyncMock(return_value=(
        [
            "[File: docs/runbook.md]\n\nworkspace fact",
        ],
        0.77,
    ))

    with patch("app.agent.fs_indexer.retrieve_filesystem_context", new=retrieve_mock), \
         patch("app.services.workspace_indexing.resolve_indexing", return_value={
             "embedding_model": "text-embedding-3-small",
             "patterns": ["**/*.md"],
             "similarity_threshold": 0.3,
             "top_k": 8,
             "watch": False,
             "cooldown_seconds": 60,
             "include_bots": [],
             "segments": [],
             "segments_source": "default",
         }), \
         patch("app.services.workspace_indexing.get_all_roots", return_value=["/data/shared/ws-1"]):
        events = await _collect(_inject_workspace_rag(
            messages,
            bot,
            SimpleNamespace(workspace_rag=True),
            "ch-1",
            "query",
            None,
            None,
            None,
            ledger,
            memory_scheme_injected_paths=set(),
            excluded_path_prefixes={"channels/ch-1/knowledge-base", "bots/bot-1/knowledge-base"},
            context_profile=SimpleNamespace(allow_workspace_rag=True),
        ))

    retrieve_mock.assert_called_once()
    call = retrieve_mock.call_args
    assert set(call.kwargs["exclude_path_prefixes"]) == {
        "channels/ch-1/knowledge-base",
        "bots/bot-1/knowledge-base",
    }
    assert events == [{"type": "fs_context", "count": 1}]
    assert len(messages) == 1
    assert "docs/runbook.md" in messages[0]["content"]
    assert ledger.inject_decisions["workspace_rag"] == "admitted"


@pytest.mark.asyncio
async def test_user_knowledge_retrieval_filters_by_owner_scope_and_status():
    bot = _make_bot(shared_workspace_id="ws-1")
    messages: list[dict] = []
    ledger = AssemblyLedger()
    retrieve_mock = AsyncMock(return_value=(
        ["[File: users/user-1/knowledge-base/notes/preferences.md]\n\nPrefers concise bullets"],
        0.79,
    ))

    with patch("app.agent.fs_indexer.retrieve_filesystem_context", new=retrieve_mock), \
         patch("app.services.workspace_indexing.resolve_indexing", return_value={
             "embedding_model": "text-embedding-3-small",
             "patterns": ["**/*.md"],
             "similarity_threshold": 0.3,
             "top_k": 8,
             "watch": False,
             "cooldown_seconds": 60,
             "include_bots": [],
             "segments": [],
             "segments_source": "default",
         }), \
         patch("app.services.workspace_indexing.get_all_roots", return_value=["/data/shared/ws-1"]):
        events = await _collect(_inject_user_knowledge(messages, bot, "format?", ledger))

    call = retrieve_mock.call_args
    assert call.kwargs["include_path_prefixes"] == ["users/user-1/knowledge-base/notes"]
    assert call.kwargs["metadata_equals"] == {
        "knowledge_scope": "user",
        "owner_user_id": "user-1",
    }
    assert call.kwargs["metadata_not_equals"] == {"kd_status": "pending_review"}
    assert events == [{"type": "user_knowledge", "count": 1, "similarity": 0.79}]
    assert "Accepted user knowledge" in messages[0]["content"]


@pytest.mark.asyncio
async def test_user_knowledge_retrieval_uses_current_bot_owner_not_other_users():
    bot = _make_bot(shared_workspace_id="ws-1")
    bot.user_id = "user-2"
    ledger = AssemblyLedger()
    retrieve_mock = AsyncMock(return_value=([], 0.0))

    with patch("app.agent.fs_indexer.retrieve_filesystem_context", new=retrieve_mock), \
         patch("app.services.workspace_indexing.resolve_indexing", return_value={
             "embedding_model": "text-embedding-3-small",
             "patterns": ["**/*.md"],
             "similarity_threshold": 0.3,
             "top_k": 8,
             "watch": False,
             "cooldown_seconds": 60,
             "include_bots": [],
             "segments": [],
             "segments_source": "default",
         }), \
         patch("app.services.workspace_indexing.get_all_roots", return_value=["/data/shared/ws-1"]):
        events = await _collect(_inject_user_knowledge([], bot, "query", ledger))

    call = retrieve_mock.call_args
    assert call.kwargs["include_path_prefixes"] == ["users/user-2/knowledge-base/notes"]
    assert call.kwargs["metadata_equals"]["owner_user_id"] == "user-2"
    assert "user-1" not in call.kwargs["include_path_prefixes"][0]
    assert events == []
    assert ledger.inject_decisions["user_knowledge"] == "skipped_empty"


@pytest.mark.asyncio
async def test_user_knowledge_skips_ownerless_bot():
    bot = _make_bot(shared_workspace_id="ws-1")
    bot.user_id = None
    ledger = AssemblyLedger()

    with patch("app.agent.fs_indexer.retrieve_filesystem_context", new=AsyncMock()) as retrieve_mock:
        events = await _collect(_inject_user_knowledge([], bot, "query", ledger))

    retrieve_mock.assert_not_called()
    assert events == []
    assert ledger.inject_decisions["user_knowledge"] == "skipped_ownerless"
