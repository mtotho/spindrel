import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.memory_search import MemorySearchResult

pytestmark = pytest.mark.asyncio


def _bot():
    return SimpleNamespace(id="bot-1", workspace=SimpleNamespace(enabled=True))


async def test_channel_archive_search_without_context_returns_error_json():
    from app.tools.local.channel_workspace import search_channel_archive

    data = json.loads(await search_channel_archive("notes"))

    assert data["count"] == 0
    assert data["results"] == []
    assert "error" in data


async def test_channel_workspace_search_uses_project_surface_scope():
    from app.tools.local.channel_workspace import search_channel_workspace

    surface = SimpleNamespace(
        index_prefix="common/projects/demo",
        index_root_host_path="/workspaces/shared/ws-1",
    )
    hybrid = AsyncMock(return_value=[
        MemorySearchResult("common/projects/demo/notes.md", "project note", 0.9),
    ])

    async def _roots(channel_id=None):
        return _bot(), "channel-1", "/workspaces/channels/channel-1", "text-embedding-3-small", surface

    with (
        patch("app.tools.local.channel_workspace._get_bot_and_roots", _roots),
        patch("app.services.memory_search.hybrid_memory_search", hybrid),
    ):
        data = json.loads(await search_channel_workspace("notes"))

    assert data["count"] == 1
    call = hybrid.await_args.kwargs
    assert call["roots"] == ["/workspaces/shared/ws-1"]
    assert call["memory_prefix"] == "common/projects/demo"


async def test_channel_knowledge_search_uses_project_surface_kb_scope():
    from app.tools.local.channel_workspace import search_channel_knowledge

    surface = SimpleNamespace(
        knowledge_index_prefix="common/projects/demo/.spindrel/knowledge-base",
        index_root_host_path="/workspaces/shared/ws-1",
    )
    hybrid = AsyncMock(return_value=[
        MemorySearchResult("common/projects/demo/.spindrel/knowledge-base/facts.md", "fact", 0.8),
    ])

    async def _roots(channel_id=None):
        return _bot(), "channel-1", "/workspaces/channels/channel-1", "text-embedding-3-small", surface

    with (
        patch("app.tools.local.channel_workspace._get_bot_and_roots", _roots),
        patch("app.services.memory_search.hybrid_memory_search", hybrid),
    ):
        data = json.loads(await search_channel_knowledge("facts"))

    assert data["count"] == 1
    call = hybrid.await_args.kwargs
    assert call["roots"] == ["/workspaces/shared/ws-1"]
    assert call["memory_prefix"] == "common/projects/demo/.spindrel/knowledge-base"
