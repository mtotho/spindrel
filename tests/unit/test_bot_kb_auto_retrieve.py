"""Tests for implicit bot knowledge-base retrieval in context_assembly."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.context_assembly import (
    AssemblyLedger,
    _inject_bot_knowledge_base,
    _inject_bot_memory_reference,
    _inject_workspace_rag,
)
from app.agent.fs_indexer import FsRetrievalChunk


def _chunk(file_path: str, content: str, similarity: float = 0.8) -> FsRetrievalChunk:
    formatted = f"[File: {file_path}]\n\n{content}"
    return FsRetrievalChunk(
        file_path=file_path,
        similarity=similarity,
        chars=len(formatted),
        formatted=formatted,
    )


def _make_bot(
    *,
    shared_workspace_id: str | None = None,
    auto_retrieval: bool = True,
    memory_reference_retrieval: bool = True,
    memory_scheme: str | None = "workspace-files",
):
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
        bot_memory_reference_auto_retrieval=memory_reference_retrieval,
    )
    return SimpleNamespace(
        id="bot-1",
        shared_workspace_id=shared_workspace_id,
        workspace=ws,
        _workspace_raw={"indexing": {}},
        _ws_indexing_config=None,
        local_tools=["search_bot_knowledge"],
        user_id="user-1",
        memory_scheme=memory_scheme,
    )


async def _collect(gen):
    return [e async for e in gen]


@pytest.mark.asyncio
async def test_bot_kb_auto_retrieval_uses_implicit_kb_segment():
    bot = _make_bot(shared_workspace_id="ws-1")
    messages: list[dict] = []
    ledger = AssemblyLedger()
    chunk = _chunk("bots/bot-1/knowledge-base/facts.md", "Important fact", similarity=0.82)
    retrieve_mock = AsyncMock(return_value=([chunk], 0.82))

    with patch("app.agent.fs_indexer.retrieve_filesystem_chunks", new=retrieve_mock), \
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
    assert len(events) == 1
    assert events[0]["type"] == "bot_knowledge_base"
    assert events[0]["count"] == 1
    assert events[0]["similarity"] == 0.82
    assert events[0]["chunks"] == [{
        "file_path": "bots/bot-1/knowledge-base/facts.md",
        "similarity": 0.82,
        "chars": chunk.chars,
    }]


@pytest.mark.asyncio
async def test_bot_kb_auto_retrieval_respects_toggle_off():
    bot = _make_bot(auto_retrieval=False)
    ledger = AssemblyLedger()

    with patch("app.agent.fs_indexer.retrieve_filesystem_chunks", new=AsyncMock()) as retrieve_mock:
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

    chunk = _chunk("knowledge-base/facts.md", "Important fact", similarity=0.71)
    with patch("app.agent.fs_indexer.retrieve_filesystem_chunks", new=AsyncMock(return_value=(
        [chunk],
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

    with patch("app.agent.fs_indexer.retrieve_filesystem_chunks", new=AsyncMock()) as retrieve_mock:
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


# ---------------------------------------------------------------------------
# bot_memory_reference (P1: semantic auto-retrieval on memory/reference/)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bot_memory_reference_admits_chunks_and_skips_directory_listing(tmp_path, monkeypatch):
    """Semantic retrieval admits the relevant reference excerpt and the listing is suppressed."""
    bot = _make_bot(shared_workspace_id="ws-1")
    messages: list[dict] = []
    ledger = AssemblyLedger()
    chunk = _chunk(
        "bots/bot-1/memory/reference/plant-profiles.md",
        "Basil prefers full sun and damp soil.",
        similarity=0.79,
    )
    retrieve_mock = AsyncMock(return_value=([chunk], 0.79))

    # Even if a reference dir exists on disk, an admitted retrieval should
    # short-circuit before the directory-listing fallback runs.
    ref_dir = tmp_path / "memory" / "reference"
    ref_dir.mkdir(parents=True)
    (ref_dir / "plant-profiles.md").write_text("# Basil\n\nLikes sun.\n")
    monkeypatch.setattr(
        "app.services.memory_scheme.get_memory_root", lambda bot, **_: str(tmp_path / "memory")
    )

    with patch("app.agent.fs_indexer.retrieve_filesystem_chunks", new=retrieve_mock), \
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
        events = await _collect(_inject_bot_memory_reference(
            messages,
            bot,
            "how should I prune my basil?",
            ledger,
            context_profile=SimpleNamespace(allow_memory_recent_logs=True),
        ))

    retrieve_mock.assert_called_once()
    call = retrieve_mock.call_args
    assert call.kwargs["include_path_prefixes"] == ["bots/bot-1/memory/reference"]
    assert call.kwargs["segments"] == [{
        "path_prefix": "bots/bot-1/memory/reference",
        "embedding_model": "text-embedding-3-small",
    }]
    assert ledger.inject_decisions["bot_memory_reference"] == "admitted"
    # No directory-listing decision recorded — retrieval admitted, listing skipped entirely.
    assert "memory_reference_index" not in ledger.inject_decisions
    assert len(events) == 1
    assert events[0]["type"] == "bot_memory_reference"
    assert events[0]["count"] == 1
    assert events[0]["chunks"] == [{
        "file_path": "bots/bot-1/memory/reference/plant-profiles.md",
        "similarity": 0.79,
        "chars": chunk.chars,
    }]
    assert any("plant-profiles.md" in m["content"] for m in messages)


@pytest.mark.asyncio
async def test_bot_memory_reference_falls_back_to_directory_listing_when_empty(tmp_path, monkeypatch):
    """Empty retrieval keeps the directory listing visible so get_memory_file still works."""
    bot = _make_bot(shared_workspace_id="ws-1")
    messages: list[dict] = []
    ledger = AssemblyLedger()
    retrieve_mock = AsyncMock(return_value=([], 0.0))

    ref_dir = tmp_path / "memory" / "reference"
    ref_dir.mkdir(parents=True)
    (ref_dir / "season-notes.md").write_text("# Season notes\n\nSpring plantings.\n")
    monkeypatch.setattr(
        "app.services.memory_scheme.get_memory_root", lambda bot, **_: str(tmp_path / "memory")
    )

    with patch("app.agent.fs_indexer.retrieve_filesystem_chunks", new=retrieve_mock), \
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
        events = await _collect(_inject_bot_memory_reference(
            messages,
            bot,
            "what's the spring plan?",
            ledger,
            context_profile=SimpleNamespace(allow_memory_recent_logs=True),
        ))

    assert ledger.inject_decisions["bot_memory_reference"] == "skipped_empty"
    assert ledger.inject_decisions["memory_reference_index"] == "admitted"
    listing_msg = next(m for m in messages if "Reference documents" in m["content"])
    assert "season-notes.md" in listing_msg["content"]
    assert events == [{"type": "memory_scheme_reference_index", "count": 1}]


@pytest.mark.asyncio
async def test_bot_memory_reference_respects_toggle_off(tmp_path, monkeypatch):
    """Toggle off → no retrieval is attempted; the listing still surfaces as fallback."""
    bot = _make_bot(shared_workspace_id="ws-1", memory_reference_retrieval=False)
    messages: list[dict] = []
    ledger = AssemblyLedger()
    retrieve_mock = AsyncMock()

    ref_dir = tmp_path / "memory" / "reference"
    ref_dir.mkdir(parents=True)
    (ref_dir / "garden-notes.md").write_text("# Garden notes\n")
    monkeypatch.setattr(
        "app.services.memory_scheme.get_memory_root", lambda bot, **_: str(tmp_path / "memory")
    )

    with patch("app.agent.fs_indexer.retrieve_filesystem_chunks", new=retrieve_mock):
        events = await _collect(_inject_bot_memory_reference(
            messages,
            bot,
            "anything?",
            ledger,
            context_profile=SimpleNamespace(allow_memory_recent_logs=True),
        ))

    retrieve_mock.assert_not_called()
    assert ledger.inject_decisions["bot_memory_reference"] == "skipped_disabled"
    assert ledger.inject_decisions["memory_reference_index"] == "admitted"
    assert any("garden-notes.md" in m["content"] for m in messages)
    assert events == [{"type": "memory_scheme_reference_index", "count": 1}]


@pytest.mark.asyncio
async def test_bot_memory_reference_respects_profile_gate():
    """Profile that disallows recent memory logs gates retrieval and listing alike."""
    bot = _make_bot(shared_workspace_id="ws-1")
    ledger = AssemblyLedger()
    retrieve_mock = AsyncMock()

    with patch("app.agent.fs_indexer.retrieve_filesystem_chunks", new=retrieve_mock):
        events = await _collect(_inject_bot_memory_reference(
            [],
            bot,
            "anything?",
            ledger,
            context_profile=SimpleNamespace(allow_memory_recent_logs=False),
        ))

    retrieve_mock.assert_not_called()
    assert events == []
    assert ledger.inject_decisions["bot_memory_reference"] == "skipped_by_profile"


@pytest.mark.asyncio
async def test_bot_memory_reference_listing_surfaces_frontmatter_summary(tmp_path, monkeypatch):
    """When retrieval misses, the directory-listing fallback must show frontmatter summaries."""
    bot = _make_bot(shared_workspace_id="ws-1")
    messages: list[dict] = []
    ledger = AssemblyLedger()
    retrieve_mock = AsyncMock(return_value=([], 0.0))

    ref_dir = tmp_path / "memory" / "reference"
    ref_dir.mkdir(parents=True)
    (ref_dir / "plant-profiles.md").write_text(
        "---\nsummary: Per-plant care notes for kitchen, sunroom, and patio plants.\n---\n\n# Plants\n"
    )
    (ref_dir / "season-notes.md").write_text("# Season notes (no frontmatter)\n")
    monkeypatch.setattr(
        "app.services.memory_scheme.get_memory_root", lambda bot, **_: str(tmp_path / "memory")
    )

    with patch("app.agent.fs_indexer.retrieve_filesystem_chunks", new=retrieve_mock), \
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
        await _collect(_inject_bot_memory_reference(
            messages,
            bot,
            "anything?",
            ledger,
            context_profile=SimpleNamespace(allow_memory_recent_logs=True),
        ))

    listing_msg = next(m for m in messages if "Reference documents" in m["content"])
    body = listing_msg["content"]
    assert "plant-profiles.md" in body
    assert "Per-plant care notes for kitchen" in body
    # File without frontmatter shouldn't synthesize a summary line.
    assert "season-notes.md" in body
    season_line = next(l for l in body.splitlines() if "season-notes.md" in l)
    assert "—" not in season_line


@pytest.mark.asyncio
async def test_bot_memory_reference_standalone_bot_uses_no_bots_prefix(tmp_path, monkeypatch):
    """Standalone bots use the bare ``memory/reference`` prefix, mirroring KB scope semantics."""
    bot = _make_bot(shared_workspace_id=None)
    ledger = AssemblyLedger()
    chunk = _chunk(
        "memory/reference/recipes.md",
        "Sourdough hydration: 75%.",
        similarity=0.81,
    )
    retrieve_mock = AsyncMock(return_value=([chunk], 0.81))

    monkeypatch.setattr(
        "app.services.memory_scheme.get_memory_root", lambda bot, **_: str(tmp_path / "memory")
    )

    with patch("app.agent.fs_indexer.retrieve_filesystem_chunks", new=retrieve_mock), \
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
        events = await _collect(_inject_bot_memory_reference(
            [],
            bot,
            "what hydration?",
            ledger,
            context_profile=SimpleNamespace(allow_memory_recent_logs=True),
        ))

    call = retrieve_mock.call_args
    assert call.kwargs["include_path_prefixes"] == ["memory/reference"]
    assert ledger.inject_decisions["bot_memory_reference"] == "admitted"
    assert events[0]["chunks"][0]["file_path"] == "memory/reference/recipes.md"


