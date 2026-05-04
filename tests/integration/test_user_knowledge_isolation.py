"""Cross-user Knowledge Document isolation contract tests."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.context import current_bot_id
from app.agent.context_assembly import AssemblyLedger, _inject_user_knowledge, _inject_workspace_rag


U1_SECRET = "[File: users/u1/knowledge-base/notes/secret.md]\n\nu1 private preference"


def _bot(user_id: str):
    indexing = SimpleNamespace(
        enabled=True,
        patterns=["**/*.md"],
        similarity_threshold=0.3,
        top_k=8,
        watch=False,
        cooldown_seconds=60,
        embedding_model=None,
        segments=[],
    )
    workspace = SimpleNamespace(
        enabled=True,
        indexing=indexing,
        bot_knowledge_auto_retrieval=True,
    )
    return SimpleNamespace(
        id=f"bot-{user_id}",
        user_id=user_id,
        shared_workspace_id="ws-shared",
        workspace=workspace,
        _workspace_raw={"indexing": {}},
        _ws_indexing_config=None,
        local_tools=["search_workspace"],
        filesystem_indexes=[],
    )


async def _collect(gen):
    return [event async for event in gen]


@pytest.mark.asyncio
async def test_user_knowledge_for_u1_does_not_reach_u2_context_or_workspace_search():
    """A u1 Knowledge Document must not leak to u2 through explicit or generic retrieval."""
    bot_u2 = _bot("u2")

    async def guarded_retrieve(*_args, **kwargs):
        include = kwargs.get("include_path_prefixes") or []
        exclude = kwargs.get("exclude_path_prefixes") or []
        metadata_equals = kwargs.get("metadata_equals") or {}

        if include:
            owner_is_u2 = metadata_equals.get("owner_user_id") == "u2"
            prefix_is_u2 = include == ["users/u2/knowledge-base/notes"]
            return ([], 0.0) if owner_is_u2 and prefix_is_u2 else ([U1_SECRET], 0.99)

        return ([], 0.0) if "users" in exclude else ([U1_SECRET], 0.99)

    retrieve_mock = AsyncMock(side_effect=guarded_retrieve)
    indexing_config = {
        "embedding_model": "text-embedding-3-small",
        "patterns": ["**/*.md"],
        "similarity_threshold": 0.3,
        "top_k": 8,
        "watch": False,
        "cooldown_seconds": 60,
        "include_bots": [],
        "segments": [],
        "segments_source": "default",
    }

    with patch("app.agent.fs_indexer.retrieve_filesystem_context", new=retrieve_mock), \
         patch("app.services.workspace_indexing.resolve_indexing", return_value=indexing_config), \
         patch("app.services.workspace_indexing.get_all_roots", return_value=["/data/shared/ws-shared"]):
        messages: list[dict] = []
        user_events = await _collect(_inject_user_knowledge(messages, bot_u2, "what do you know?", AssemblyLedger()))
        assert user_events == []
        assert not messages

        rag_messages: list[dict] = []
        rag_events = await _collect(_inject_workspace_rag(
            rag_messages,
            bot_u2,
            SimpleNamespace(workspace_rag=True),
            None,
            "what do you know?",
            None,
            None,
            None,
            AssemblyLedger(),
            memory_scheme_injected_paths=set(),
            excluded_path_prefixes={"users"},
            context_profile=SimpleNamespace(allow_workspace_rag=True),
        ))
        assert rag_events == []
        assert not rag_messages

        tok = current_bot_id.set(bot_u2.id)
        try:
            from app.tools.local.workspace import search_workspace

            with patch("app.agent.bots.get_bot", return_value=bot_u2), \
                 patch("app.tools.local.workspace.current_bot_id", MagicMock(get=MagicMock(return_value=bot_u2.id))):
                search_result = await search_workspace("private preference")
        finally:
            current_bot_id.reset(tok)

        assert "u1 private preference" not in search_result

    calls = [call.kwargs for call in retrieve_mock.await_args_list]
    assert any(call.get("include_path_prefixes") == ["users/u2/knowledge-base/notes"] for call in calls)
    assert sum("users" in (call.get("exclude_path_prefixes") or []) for call in calls) >= 2
