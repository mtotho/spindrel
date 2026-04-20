"""Schema validation tests for Tier-1 tool JSON backfill.

Verifies that each refactored tool:
1. Returns valid JSON
2. Matches the declared returns schema in the registry
3. Handles both happy-path and no-results cases structurally

Tools covered:
- search_channel_archive, search_channel_workspace, search_channel_knowledge (channel_workspace.py)
- search_workspace, search_bot_knowledge (workspace.py)
- search_memory, search_bot_memory, get_memory_file (memory_files.py)
- get_skill, get_skill_list (skills.py)
- list_channels (channel_workspace.py)
- summarize_channel (summarize_channel.py)
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import jsonschema
import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate(result: str, tool_name: str) -> dict:
    """Parse result as JSON and validate against the tool's declared returns schema."""
    from app.tools.registry import _tools
    data = json.loads(result)
    schema = _tools[tool_name].get("returns")
    if schema:
        jsonschema.validate(data, schema)
    return data


def _make_memory_result(file_path="memory/MEMORY.md", content="some content", score=0.85):
    from app.services.memory_search import MemorySearchResult
    return MemorySearchResult(file_path=file_path, content=content, score=score)


def _make_bot(cross_workspace_access=False, shared_workspace_role="worker", memory_scheme="workspace-files"):
    ws_indexing = SimpleNamespace(
        enabled=True, patterns=["**/*.md"], similarity_threshold=0.3, top_k=10,
        watch=False, cooldown_seconds=60, embedding_model=None, segments=None,
    )
    ws = SimpleNamespace(enabled=True, indexing=ws_indexing)
    return SimpleNamespace(
        id="test_bot",
        cross_workspace_access=cross_workspace_access,
        shared_workspace_role=shared_workspace_role,
        memory_scheme=memory_scheme,
        workspace=ws,
        _workspace_raw={"indexing": {}},
        _ws_indexing_config=None,
        pinned_tools=[], skills=[], skill_ids=[], local_tools=[],
        client_tools=[], mcp_servers=[],
    )


# ---------------------------------------------------------------------------
# search_channel_archive
# ---------------------------------------------------------------------------

class TestSearchChannelArchive:
    async def test_no_context_returns_error_json(self):
        from app.tools.local.channel_workspace import search_channel_archive
        with (
            patch("app.tools.local.channel_workspace.current_bot_id", MagicMock(get=MagicMock(return_value=None))),
            patch("app.tools.local.channel_workspace.current_channel_id", MagicMock(get=MagicMock(return_value=None))),
        ):
            result = await search_channel_archive("test query")
        data = _validate(result, "search_channel_archive")
        assert data["count"] == 0
        assert "error" in data

    async def test_no_results_returns_structured_empty(self):
        from app.tools.local.channel_workspace import search_channel_archive
        bot = _make_bot()
        ch_id = str(uuid.uuid4())

        async def _mock_get_bot_and_roots(*a, **kw):
            return bot, ch_id, "/workspace", "text-embedding-3-small"

        with (
            patch("app.tools.local.channel_workspace._get_bot_and_roots", _mock_get_bot_and_roots),
            patch("app.services.channel_workspace.get_channel_workspace_index_prefix", return_value="channels/ch-1"),
            patch("app.services.channel_workspace_indexing._get_channel_index_bot_id", return_value="channel:ch-1"),
            patch("app.services.memory_search.hybrid_memory_search", AsyncMock(return_value=[])),
            patch("asyncio.create_task"),
        ):
            result = await search_channel_archive("missing topic")
        data = _validate(result, "search_channel_archive")
        assert data["count"] == 0
        assert data["results"] == []
        assert "message" in data

    async def test_results_match_schema(self):
        from app.tools.local.channel_workspace import search_channel_archive
        bot = _make_bot()
        ch_id = str(uuid.uuid4())
        mock_results = [_make_memory_result("channels/ch-1/archive/doc.md", "chunk content", 0.91)]

        async def _mock_get_bot_and_roots(*a, **kw):
            return bot, ch_id, "/workspace", "text-embedding-3-small"

        with (
            patch("app.tools.local.channel_workspace._get_bot_and_roots", _mock_get_bot_and_roots),
            patch("app.services.channel_workspace.get_channel_workspace_index_prefix", return_value="channels/ch-1"),
            patch("app.services.channel_workspace_indexing._get_channel_index_bot_id", return_value="channel:ch-1"),
            patch("app.services.memory_search.hybrid_memory_search", AsyncMock(return_value=mock_results)),
        ):
            result = await search_channel_archive("doc query")
        data = _validate(result, "search_channel_archive")
        assert data["count"] == 1
        assert data["results"][0]["file_path"] == "channels/ch-1/archive/doc.md"
        assert data["results"][0]["score"] == 0.91
        assert "snippet" in data["results"][0]


# ---------------------------------------------------------------------------
# search_channel_workspace
# ---------------------------------------------------------------------------

class TestSearchChannelWorkspace:
    async def test_results_match_schema(self):
        from app.tools.local.channel_workspace import search_channel_workspace
        bot = _make_bot()
        ch_id = str(uuid.uuid4())
        mock_results = [_make_memory_result("channels/ch-1/notes.md", "# Notes\nsome content", 0.75)]

        async def _mock_get_bot_and_roots(channel_id=None):
            return bot, str(ch_id), "/workspace", "text-embedding-3-small"

        with (
            patch("app.tools.local.channel_workspace._get_bot_and_roots", _mock_get_bot_and_roots),
            patch("app.services.channel_workspace.get_channel_workspace_index_prefix", return_value="channels/ch-1"),
            patch("app.services.channel_workspace_indexing._get_channel_index_bot_id", return_value="channel:ch-1"),
            patch("app.services.memory_search.hybrid_memory_search", AsyncMock(return_value=mock_results)),
        ):
            result = await search_channel_workspace("notes")
        data = _validate(result, "search_channel_workspace")
        assert data["count"] == 1
        # Header line stripped (starts with "# ")
        assert not data["results"][0]["snippet"].startswith("# ")


# ---------------------------------------------------------------------------
# search_channel_knowledge
# ---------------------------------------------------------------------------

class TestSearchChannelKnowledge:
    async def test_no_results_returns_structured(self):
        from app.tools.local.channel_workspace import search_channel_knowledge
        bot = _make_bot()
        ch_id = str(uuid.uuid4())

        async def _mock_get_bot_and_roots(*a, **kw):
            return bot, str(ch_id), "/workspace", "text-embedding-3-small"

        with (
            patch("app.tools.local.channel_workspace._get_bot_and_roots", _mock_get_bot_and_roots),
            patch("app.services.channel_workspace.get_channel_knowledge_base_index_prefix", return_value="channels/ch-1/knowledge-base"),
            patch("app.services.channel_workspace_indexing._get_channel_index_bot_id", return_value="channel:ch-1"),
            patch("app.services.memory_search.hybrid_memory_search", AsyncMock(return_value=[])),
        ):
            result = await search_channel_knowledge("facts")
        data = _validate(result, "search_channel_knowledge")
        assert data["count"] == 0


# ---------------------------------------------------------------------------
# list_channels
# ---------------------------------------------------------------------------

class TestListChannels:
    async def test_no_bot_context_returns_error(self):
        from app.tools.local.channel_workspace import list_channels
        with (
            patch("app.tools.local.channel_workspace.current_bot_id", MagicMock(get=MagicMock(return_value=None))),
            patch("app.tools.local.channel_workspace.current_channel_id", MagicMock(get=MagicMock(return_value=None))),
        ):
            result = await list_channels()
        data = _validate(result, "list_channels")
        assert "error" in data

    async def test_empty_channels_returns_empty_list(self):
        from app.tools.local.channel_workspace import list_channels

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_bot = MagicMock(cross_workspace_access=False)

        with (
            patch("app.tools.local.channel_workspace.current_bot_id", MagicMock(get=MagicMock(return_value="bot-1"))),
            patch("app.tools.local.channel_workspace.current_channel_id", MagicMock(get=MagicMock(return_value=None))),
            patch("app.agent.bots.get_bot", return_value=mock_bot),
            patch("app.db.engine.async_session", return_value=mock_session),
            patch("app.services.channels.bot_channel_filter", return_value=True),
        ):
            result = await list_channels()
        data = _validate(result, "list_channels")
        assert data["count"] == 0
        assert data["channels"] == []

    async def test_channels_match_schema(self):
        from app.tools.local.channel_workspace import list_channels

        ch_uuid = uuid.uuid4()
        mock_row = MagicMock()
        mock_row.id = ch_uuid
        mock_row.name = "General"
        mock_row.client_id = "C12345"
        mock_row.bot_id = uuid.UUID("00000000-0000-0000-0000-000000000001")

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[mock_row])))
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_bot = MagicMock(cross_workspace_access=False)

        with (
            patch("app.tools.local.channel_workspace.current_bot_id", MagicMock(get=MagicMock(return_value="bot-1"))),
            patch("app.tools.local.channel_workspace.current_channel_id", MagicMock(get=MagicMock(return_value=None))),
            patch("app.agent.bots.get_bot", return_value=mock_bot),
            patch("app.db.engine.async_session", return_value=mock_session),
            patch("app.services.channels.bot_channel_filter", return_value=True),
        ):
            result = await list_channels()
        data = _validate(result, "list_channels")
        assert data["count"] == 1
        ch = data["channels"][0]
        assert ch["id"] == str(ch_uuid)
        assert ch["name"] == "General"
        assert isinstance(ch["is_current"], bool)
        assert isinstance(ch["is_member"], bool)


# ---------------------------------------------------------------------------
# search_workspace
# ---------------------------------------------------------------------------

class TestSearchWorkspace:
    async def test_no_bot_context(self):
        from app.tools.local.workspace import search_workspace
        with patch("app.tools.local.workspace.current_bot_id", MagicMock(get=MagicMock(return_value=None))):
            result = await search_workspace("query")
        data = _validate(result, "search_workspace")
        assert data["count"] == 0
        assert "error" in data

    async def test_no_results(self):
        from app.tools.local.workspace import search_workspace
        bot = _make_bot()
        with (
            patch("app.tools.local.workspace.current_bot_id", MagicMock(get=MagicMock(return_value="bot-1"))),
            patch("app.agent.bots.get_bot", return_value=bot),
            patch("app.services.workspace.workspace_service"),
            patch("app.services.workspace_indexing.resolve_indexing", return_value={"embedding_model": "text-embedding-3-small", "similarity_threshold": 0.3, "top_k": 10, "segments": None}),
            patch("app.services.workspace_indexing.get_all_roots", return_value=["/workspace"]),
            patch("app.agent.fs_indexer.retrieve_filesystem_context", AsyncMock(return_value=([], 0.0))),
        ):
            result = await search_workspace("nothing here")
        data = _validate(result, "search_workspace")
        assert data["count"] == 0
        assert "message" in data

    async def test_results_match_schema(self):
        from app.tools.local.workspace import search_workspace
        bot = _make_bot()
        chunks = ["[File: src/main.py]\n\ndef hello(): pass"]

        with (
            patch("app.tools.local.workspace.current_bot_id", MagicMock(get=MagicMock(return_value="bot-1"))),
            patch("app.agent.bots.get_bot", return_value=bot),
            patch("app.services.workspace.workspace_service"),
            patch("app.services.workspace_indexing.resolve_indexing", return_value={"embedding_model": "text-embedding-3-small", "similarity_threshold": 0.3, "top_k": 10, "segments": None}),
            patch("app.services.workspace_indexing.get_all_roots", return_value=["/workspace"]),
            patch("app.agent.fs_indexer.retrieve_filesystem_context", AsyncMock(return_value=(chunks, 0.92))),
        ):
            result = await search_workspace("hello function")
        data = _validate(result, "search_workspace")
        assert data["count"] == 1
        assert data["results"][0]["file_path"] == "src/main.py"
        assert "hello" in data["results"][0]["snippet"]
        assert data["best_similarity"] == 0.92


# ---------------------------------------------------------------------------
# search_bot_knowledge
# ---------------------------------------------------------------------------

class TestSearchBotKnowledge:
    async def test_results_match_schema(self):
        from app.tools.local.workspace import search_bot_knowledge
        bot = _make_bot()
        mock_results = [_make_memory_result("knowledge-base/facts.md", "important facts", 0.88)]

        with (
            patch("app.tools.local.workspace.current_bot_id", MagicMock(get=MagicMock(return_value="bot-1"))),
            patch("app.agent.bots.get_bot", return_value=bot),
            patch("app.services.workspace.workspace_service") as mock_ws,
            patch("app.services.workspace_indexing.resolve_indexing", return_value={"embedding_model": "text-embedding-3-small", "top_k": 10}),
            patch("app.services.workspace_indexing.get_all_roots", return_value=["/workspace"]),
            patch("app.services.memory_search.hybrid_memory_search", AsyncMock(return_value=mock_results)),
        ):
            mock_ws.get_bot_knowledge_base_index_prefix.return_value = "knowledge-base"
            result = await search_bot_knowledge("facts")
        data = _validate(result, "search_bot_knowledge")
        assert data["count"] == 1
        assert data["results"][0]["file_path"] == "knowledge-base/facts.md"


# ---------------------------------------------------------------------------
# search_memory
# ---------------------------------------------------------------------------

class TestSearchMemory:
    async def test_no_context_returns_error(self):
        from app.tools.local.memory_files import search_memory
        with patch("app.tools.local.memory_files.current_bot_id", MagicMock(get=MagicMock(return_value=None))):
            result = await search_memory("query")
        data = _validate(result, "search_memory")
        assert data["count"] == 0
        assert "error" in data

    async def test_results_match_schema(self):
        from app.tools.local.memory_files import search_memory
        bot = _make_bot()
        mock_results = [_make_memory_result("memory/MEMORY.md", "user preferences here", 0.90)]

        with (
            patch("app.tools.local.memory_files.current_bot_id", MagicMock(get=MagicMock(return_value="bot-1"))),
            patch("app.agent.bots.get_bot", return_value=bot),
            patch("app.services.workspace.workspace_service") as mock_ws,
            patch("app.services.memory_scheme.get_memory_index_prefix", return_value="memory"),
            patch("app.services.workspace_indexing.resolve_indexing", return_value={"embedding_model": "text-embedding-3-small"}),
            patch("app.services.workspace_indexing.get_all_roots", return_value=["/workspace"]),
            patch("app.services.memory_search.hybrid_memory_search", AsyncMock(return_value=mock_results)),
        ):
            mock_ws.get_workspace_root.return_value = "/workspace"
            result = await search_memory("user preferences")
        data = _validate(result, "search_memory")
        assert data["count"] == 1
        assert data["results"][0]["file_path"] == "memory/MEMORY.md"
        assert data["results"][0]["score"] == 0.9


# ---------------------------------------------------------------------------
# get_memory_file
# ---------------------------------------------------------------------------

class TestGetMemoryFile:
    async def test_file_not_found_returns_structured(self, tmp_path):
        from app.tools.local.memory_files import get_memory_file
        bot = _make_bot()

        with (
            patch("app.tools.local.memory_files.current_bot_id", MagicMock(get=MagicMock(return_value="bot-1"))),
            patch("app.agent.bots.get_bot", return_value=bot),
            patch("app.services.workspace.workspace_service") as mock_ws,
            patch("app.services.memory_scheme.get_memory_root", return_value=str(tmp_path)),
        ):
            mock_ws.get_workspace_root.return_value = str(tmp_path)
            result = await get_memory_file("nonexistent")
        data = _validate(result, "get_memory_file")
        assert "error" in data
        assert "available" in data

    async def test_file_found_returns_content(self, tmp_path):
        from app.tools.local.memory_files import get_memory_file
        bot = _make_bot()

        mem_dir = tmp_path / "memory"
        mem_dir.mkdir()
        (mem_dir / "MEMORY.md").write_text("# My Memory\n\nSome content here.")

        with (
            patch("app.tools.local.memory_files.current_bot_id", MagicMock(get=MagicMock(return_value="bot-1"))),
            patch("app.agent.bots.get_bot", return_value=bot),
            patch("app.services.workspace.workspace_service") as mock_ws,
            patch("app.services.memory_scheme.get_memory_root", return_value=str(mem_dir)),
        ):
            mock_ws.get_workspace_root.return_value = str(tmp_path)
            result = await get_memory_file("MEMORY")
        data = _validate(result, "get_memory_file")
        assert "path" in data
        assert "MEMORY.md" in data["path"]
        assert "Some content here." in data["content"]


# ---------------------------------------------------------------------------
# search_bot_memory
# ---------------------------------------------------------------------------

class TestSearchBotMemory:
    async def test_orchestrator_gate(self):
        from app.tools.local.memory_files import search_bot_memory
        bot = _make_bot(shared_workspace_role="worker")

        with (
            patch("app.tools.local.memory_files.current_bot_id", MagicMock(get=MagicMock(return_value="bot-1"))),
            patch("app.agent.bots.get_bot", return_value=bot),
            patch("app.services.workspace.workspace_service") as mock_ws,
        ):
            mock_ws.get_workspace_root.return_value = "/workspace"
            result = await search_bot_memory("bot-2", "query")
        data = _validate(result, "search_bot_memory")
        assert data["count"] == 0
        assert "error" in data

    async def test_results_match_schema(self):
        from app.tools.local.memory_files import search_bot_memory
        caller_bot = _make_bot(shared_workspace_role="orchestrator")
        target_bot = _make_bot()
        target_bot.id = "bot-2"
        target_bot.memory_scheme = "workspace-files"

        mock_results = [_make_memory_result("memory/MEMORY.md", "target bot facts", 0.80)]

        with (
            patch("app.tools.local.memory_files.current_bot_id", MagicMock(get=MagicMock(return_value="bot-1"))),
            patch("app.agent.bots.get_bot", side_effect=lambda bid: caller_bot if bid == "bot-1" else target_bot),
            patch("app.services.workspace.workspace_service") as mock_ws,
            patch("app.services.memory_scheme.get_memory_index_prefix", return_value="memory"),
            patch("app.services.workspace_indexing.resolve_indexing", return_value={"embedding_model": "text-embedding-3-small"}),
            patch("app.services.workspace_indexing.get_all_roots", return_value=["/workspace"]),
            patch("app.services.memory_search.hybrid_memory_search", AsyncMock(return_value=mock_results)),
        ):
            mock_ws.get_workspace_root.return_value = "/workspace"
            result = await search_bot_memory("bot-2", "facts")
        data = _validate(result, "search_bot_memory")
        assert data["count"] == 1
        assert data["results"][0]["file_path"] == "memory/MEMORY.md"


# ---------------------------------------------------------------------------
# get_skill
# ---------------------------------------------------------------------------

class TestGetSkill:
    async def test_skill_not_found_returns_structured(self):
        from app.tools.local.skills import get_skill

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.tools.local.skills.current_bot_id", MagicMock(get=MagicMock(return_value="bot-1"))),
            patch("app.tools.local.skills.async_session", return_value=mock_session),
        ):
            result = await get_skill("nonexistent_skill")
        data = _validate(result, "get_skill")
        assert data["id"] == "nonexistent_skill"
        assert "error" in data

    async def test_skill_found_returns_content(self):
        from app.tools.local.skills import get_skill

        mock_row = MagicMock()
        mock_row.name = "My Skill"
        mock_row.content = "Skill body here."
        mock_row.archived_at = None

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=mock_row)
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.tools.local.skills.current_bot_id", MagicMock(get=MagicMock(return_value="bot-1"))),
            patch("app.tools.local.skills.async_session", return_value=mock_session),
            patch("app.services.skill_enrollment._upsert_ignore", return_value=(MagicMock(), MagicMock())),
            patch("app.services.skill_enrollment._pick_stmt", return_value=MagicMock()),
            patch("app.services.skill_enrollment.invalidate_enrolled_cache"),
            patch("asyncio.create_task"),
        ):
            result = await get_skill("my_skill")
        data = _validate(result, "get_skill")
        assert data["id"] == "my_skill"
        assert data["name"] == "My Skill"
        assert data["content"] == "Skill body here."


# ---------------------------------------------------------------------------
# get_skill_list
# ---------------------------------------------------------------------------

class TestGetSkillList:
    async def test_empty_returns_structured(self):
        from app.tools.local.skills import get_skill_list

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.tools.local.skills.current_bot_id", MagicMock(get=MagicMock(return_value="bot-1"))),
            patch("app.tools.local.skills.async_session", return_value=mock_session),
        ):
            result = await get_skill_list()
        data = _validate(result, "get_skill_list")
        assert data["count"] == 0
        assert data["skills"] == []

    async def test_skills_match_schema(self):
        from app.tools.local.skills import get_skill_list

        mock_row = MagicMock()
        mock_row.id = "my_skill"
        mock_row.name = "My Skill"
        mock_row.description = "Does stuff"
        mock_row.triggers = ["trigger_one"]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[mock_row])))
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.tools.local.skills.current_bot_id", MagicMock(get=MagicMock(return_value="bot-1"))),
            patch("app.tools.local.skills.async_session", return_value=mock_session),
        ):
            result = await get_skill_list()
        data = _validate(result, "get_skill_list")
        assert data["count"] == 1
        skill = data["skills"][0]
        assert skill["id"] == "my_skill"
        assert skill["name"] == "My Skill"
        assert skill["description"] == "Does stuff"
        assert "trigger_one" in skill["triggers"]


# ---------------------------------------------------------------------------
# summarize_channel (schema validation)
# ---------------------------------------------------------------------------

class TestSummarizeChannelSchema:
    async def test_success_matches_schema(self):
        import uuid
        from app.tools.local.summarize_channel import summarize_channel

        ch_id = uuid.uuid4()
        with (
            patch("app.tools.local.summarize_channel.current_channel_id", MagicMock(get=MagicMock(return_value=ch_id))),
            patch("app.services.summarizer.summarize_messages", AsyncMock(return_value="The summary text.")),
        ):
            result = await summarize_channel()
        data = _validate(result, "summarize_channel")
        assert data["summary"] == "The summary text."
