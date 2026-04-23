"""Tests for implicit bot knowledge-base retrieval in context_assembly."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.context_assembly import _inject_bot_knowledge_base, _inject_workspace_rag


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
    )


async def _collect(gen):
    return [e async for e in gen]


@pytest.mark.asyncio
async def test_bot_kb_auto_retrieval_uses_implicit_kb_segment():
    bot = _make_bot(shared_workspace_id="ws-1")
    messages: list[dict] = []
    inject_chars: dict[str, int] = {}
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
            inject_chars,
            budget_consume=lambda k, v: None,
            budget_can_afford=lambda _: True,
            context_profile=SimpleNamespace(allow_bot_knowledge_base=True),
            inject_decisions={},
        ))

    retrieve_mock.assert_called_once()
    call = retrieve_mock.call_args
    assert call.kwargs["segments"] == [{
        "path_prefix": "bots/bot-1/knowledge-base",
        "embedding_model": "text-embedding-3-small",
    }]
    assert any("search_bot_knowledge" in m["content"] for m in messages)
    assert inject_chars["bot_knowledge_base"] > 0
    assert events == [{"type": "bot_knowledge_base", "count": 1, "similarity": 0.82}]


@pytest.mark.asyncio
async def test_bot_kb_auto_retrieval_respects_toggle_off():
    bot = _make_bot(auto_retrieval=False)
    inject_decisions: dict[str, str] = {}

    with patch("app.agent.fs_indexer.retrieve_filesystem_context", new=AsyncMock()) as retrieve_mock:
        events = await _collect(_inject_bot_knowledge_base(
            [],
            bot,
            "query",
            {},
            budget_consume=lambda k, v: None,
            budget_can_afford=lambda _: True,
            context_profile=SimpleNamespace(allow_bot_knowledge_base=True),
            inject_decisions=inject_decisions,
        ))

    retrieve_mock.assert_not_called()
    assert events == []
    assert inject_decisions["bot_knowledge_base"] == "skipped_disabled"


@pytest.mark.asyncio
async def test_bot_kb_auto_retrieval_skips_when_budget_rejects():
    bot = _make_bot()
    messages: list[dict] = []
    inject_decisions: dict[str, str] = {}

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
            {},
            budget_consume=lambda k, v: None,
            budget_can_afford=lambda _: False,
            context_profile=SimpleNamespace(allow_bot_knowledge_base=True),
            inject_decisions=inject_decisions,
        ))

    assert events == []
    assert messages == []
    assert inject_decisions["bot_knowledge_base"] == "skipped_by_budget"


@pytest.mark.asyncio
async def test_bot_kb_auto_retrieval_respects_profile_gate():
    bot = _make_bot(auto_retrieval=True)
    inject_decisions: dict[str, str] = {}

    with patch("app.agent.fs_indexer.retrieve_filesystem_context", new=AsyncMock()) as retrieve_mock:
        events = await _collect(_inject_bot_knowledge_base(
            [],
            bot,
            "query",
            {},
            budget_consume=lambda k, v: None,
            budget_can_afford=lambda _: True,
            context_profile=SimpleNamespace(allow_bot_knowledge_base=False),
            inject_decisions=inject_decisions,
        ))

    retrieve_mock.assert_not_called()
    assert events == []
    assert inject_decisions["bot_knowledge_base"] == "skipped_by_profile"


@pytest.mark.asyncio
async def test_workspace_rag_excludes_dedicated_channel_and_bot_kb_chunks():
    bot = _make_bot(shared_workspace_id="ws-1")
    messages: list[dict] = []
    inject_decisions: dict[str, str] = {}
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
            {},
            budget_consume=lambda k, v: None,
            budget_can_afford=lambda _: True,
            budget=None,
            memory_scheme_injected_paths=set(),
            excluded_path_prefixes={"channels/ch-1/knowledge-base", "bots/bot-1/knowledge-base"},
            context_profile=SimpleNamespace(allow_workspace_rag=True),
            inject_decisions=inject_decisions,
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
    assert inject_decisions["workspace_rag"] == "admitted"
