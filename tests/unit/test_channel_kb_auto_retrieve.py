"""Tests for the implicit channel knowledge-base RAG retrieval path in context_assembly.

Verifies that `_inject_channel_workspace` fires a retrieval against
`channels/{ch_id}/knowledge-base/` regardless of whether the channel has
explicit `index_segments` configured.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.context_assembly import AssemblyLedger, _inject_channel_workspace


def _make_bot():
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
        shared_workspace_id="ws-1",
        workspace=ws,
        _workspace_raw={"indexing": {}},
        _ws_indexing_config=None,
        local_tools=["search_channel_knowledge"],
        memory_scheme="workspace-files",
    )


def _make_ch_row(ch_id="ch-1", segments=None):
    return SimpleNamespace(
        id=ch_id,
        name="Test Channel",
        index_segments=segments or [],
        workspace_schema_content=None,
        workspace_schema_template_id=None,
    )


async def _collect(gen):
    return [e async for e in gen]


@pytest.mark.asyncio
async def test_implicit_kb_segment_injected_without_explicit_segments(tmp_path):
    """Channels with no index_segments still get knowledge-base retrieval."""
    bot = _make_bot()
    ch_row = _make_ch_row()

    # Fake cw_root — anything under a .parent.parent to get a roots[0] path
    fake_ws_root = str(tmp_path)
    fake_cw_root = str(tmp_path / "channels" / "ch-1")
    messages: list[dict] = []
    ledger = AssemblyLedger()

    retrieve_mock = AsyncMock(return_value=(["## some-file.md\n\nbody"], 0.7))

    with patch("app.services.channel_workspace.ensure_channel_workspace", return_value=fake_cw_root), \
         patch("app.services.channel_workspace.get_channel_workspace_root", return_value=fake_cw_root), \
         patch("app.services.channel_workspace_indexing.index_channel_workspace", new=AsyncMock(return_value=None)), \
         patch("app.agent.fs_indexer.retrieve_filesystem_context", new=retrieve_mock), \
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
        }):
        events = await _collect(_inject_channel_workspace(
            messages, bot, ch_row, "what do you know about oranges?", ledger,
            context_profile=SimpleNamespace(allow_channel_workspace=True, allow_channel_index_segments=True),
        ))

    # retrieve_filesystem_context called with an implicit KB segment
    retrieve_mock.assert_called_once()
    call = retrieve_mock.call_args
    segments = call.kwargs.get("segments") or []
    assert len(segments) == 1
    assert segments[0]["path_prefix"] == "channels/ch-1/knowledge-base"

    # The returned chunk was injected as a system message
    kb_messages = [m for m in messages if "knowledge base" in m.get("content", "")]
    assert kb_messages, f"No KB system message. messages: {messages}"

    kinds = [e["type"] for e in events]
    assert "channel_index_segments" in kinds


@pytest.mark.asyncio
async def test_explicit_segments_compose_with_implicit_kb(tmp_path):
    """A channel with explicit index_segments keeps them + gets the implicit KB segment."""
    bot = _make_bot()
    ch_row = _make_ch_row(segments=[
        {"path_prefix": "vault", "patterns": ["**/*.md"]},
    ])

    fake_cw_root = str(tmp_path / "channels" / "ch-1")
    messages: list[dict] = []

    retrieve_mock = AsyncMock(return_value=([], 0.0))

    with patch("app.services.channel_workspace.ensure_channel_workspace", return_value=fake_cw_root), \
         patch("app.services.channel_workspace.get_channel_workspace_root", return_value=fake_cw_root), \
         patch("app.services.channel_workspace_indexing.index_channel_workspace", new=AsyncMock(return_value=None)), \
         patch("app.agent.fs_indexer.retrieve_filesystem_context", new=retrieve_mock), \
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
        }):
        await _collect(_inject_channel_workspace(
            messages, bot, ch_row, "query", AssemblyLedger(),
            context_profile=SimpleNamespace(allow_channel_workspace=True, allow_channel_index_segments=True),
        ))

    call = retrieve_mock.call_args
    segments = call.kwargs.get("segments") or []
    prefixes = [s["path_prefix"] for s in segments]
    assert "channels/ch-1/knowledge-base" in prefixes
    assert "channels/ch-1/vault" in prefixes


@pytest.mark.asyncio
async def test_explicit_kb_segment_does_not_duplicate(tmp_path):
    """If the user explicitly configures a knowledge-base segment, we don't register it twice."""
    bot = _make_bot()
    ch_row = _make_ch_row(segments=[
        {"path_prefix": "knowledge-base", "patterns": ["**/*.md"], "embedding_model": "custom"},
    ])

    fake_cw_root = str(tmp_path / "channels" / "ch-1")
    messages: list[dict] = []

    retrieve_mock = AsyncMock(return_value=([], 0.0))

    with patch("app.services.channel_workspace.ensure_channel_workspace", return_value=fake_cw_root), \
         patch("app.services.channel_workspace.get_channel_workspace_root", return_value=fake_cw_root), \
         patch("app.services.channel_workspace_indexing.index_channel_workspace", new=AsyncMock(return_value=None)), \
         patch("app.agent.fs_indexer.retrieve_filesystem_context", new=retrieve_mock), \
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
        }):
        await _collect(_inject_channel_workspace(
            messages, bot, ch_row, "query", AssemblyLedger(),
            context_profile=SimpleNamespace(allow_channel_workspace=True, allow_channel_index_segments=True),
        ))

    call = retrieve_mock.call_args
    segments = call.kwargs.get("segments") or []
    prefixes = [s["path_prefix"] for s in segments]
    # Only one entry for the KB prefix — the implicit one (explicit KB dedup keeps implicit)
    assert prefixes.count("channels/ch-1/knowledge-base") == 1
