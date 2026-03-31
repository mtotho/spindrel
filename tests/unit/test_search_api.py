"""Tests for app.routers.api_v1_search — core search API."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers.api_v1_search import search_memory, MemorySearchRequest


def _make_bot(bot_id="test_bot", name="Test Bot", memory_scheme="workspace-files"):
    bot = MagicMock()
    bot.id = bot_id
    bot.name = name
    bot.memory_scheme = memory_scheme
    return bot


class TestSearchMemoryEndpoint:

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self):
        req = MemorySearchRequest(query="   ")
        result = await search_memory(req, auth=MagicMock())
        assert result.results == []

    @pytest.mark.asyncio
    @patch("app.services.memory_search.hybrid_memory_search")
    @patch("app.services.workspace.workspace_service")
    @patch("app.services.memory_scheme.get_memory_index_prefix")
    @patch("app.agent.bots.list_bots")
    @patch("app.agent.bots.get_bot")
    async def test_searches_all_memory_bots(
        self, mock_get_bot, mock_list_bots, mock_prefix, mock_ws, mock_search
    ):
        bot1 = _make_bot("b1", "Bot 1")
        bot2 = _make_bot("b2", "Bot 2", memory_scheme="none")
        mock_list_bots.return_value = [bot1, bot2]
        mock_ws.get_workspace_root.return_value = "/ws/b1"
        mock_prefix.return_value = "memory"

        hit = MagicMock()
        hit.file_path = "memory/MEMORY.md"
        hit.content = "test content"
        hit.score = 0.85
        mock_search.return_value = [hit]

        req = MemorySearchRequest(query="test query")
        result = await search_memory(req, auth=MagicMock())

        assert len(result.results) == 1
        assert result.results[0].bot_id == "b1"
        assert result.results[0].bot_name == "Bot 1"
        assert result.results[0].score == 0.85

    @pytest.mark.asyncio
    @patch("app.services.memory_search.hybrid_memory_search")
    @patch("app.services.workspace.workspace_service")
    @patch("app.services.memory_scheme.get_memory_index_prefix")
    @patch("app.agent.bots.get_bot")
    async def test_explicit_bot_ids(
        self, mock_get_bot, mock_prefix, mock_ws, mock_search
    ):
        bot1 = _make_bot("b1", "Bot 1")
        mock_get_bot.return_value = bot1
        mock_ws.get_workspace_root.return_value = "/ws/b1"
        mock_prefix.return_value = "memory"
        mock_search.return_value = []

        req = MemorySearchRequest(query="search", bot_ids=["b1"])
        result = await search_memory(req, auth=MagicMock())

        mock_get_bot.assert_called_once_with("b1")
        assert result.results == []

    @pytest.mark.asyncio
    @patch("app.services.memory_search.hybrid_memory_search")
    @patch("app.services.workspace.workspace_service")
    @patch("app.services.memory_scheme.get_memory_index_prefix")
    @patch("app.agent.bots.list_bots")
    @patch("app.agent.bots.get_bot")
    async def test_results_sorted_by_score(
        self, mock_get_bot, mock_list_bots, mock_prefix, mock_ws, mock_search
    ):
        bot1 = _make_bot("b1", "Bot 1")
        bot2 = _make_bot("b2", "Bot 2")
        mock_list_bots.return_value = [bot1, bot2]
        mock_ws.get_workspace_root.side_effect = lambda bid, bot: f"/ws/{bid}"
        mock_prefix.return_value = "memory"

        hit1 = MagicMock(file_path="memory/MEMORY.md", content="low", score=0.3)
        hit2 = MagicMock(file_path="memory/MEMORY.md", content="high", score=0.9)
        mock_search.side_effect = [[hit1], [hit2]]

        req = MemorySearchRequest(query="test", top_k=10)
        result = await search_memory(req, auth=MagicMock())

        assert len(result.results) == 2
        assert result.results[0].score == 0.9
        assert result.results[1].score == 0.3

    @pytest.mark.asyncio
    @patch("app.services.memory_search.hybrid_memory_search")
    @patch("app.services.workspace.workspace_service")
    @patch("app.services.memory_scheme.get_memory_index_prefix")
    @patch("app.agent.bots.list_bots")
    @patch("app.agent.bots.get_bot")
    async def test_top_k_limits_results(
        self, mock_get_bot, mock_list_bots, mock_prefix, mock_ws, mock_search
    ):
        bot = _make_bot("b1", "Bot 1")
        mock_list_bots.return_value = [bot]
        mock_ws.get_workspace_root.return_value = "/ws/b1"
        mock_prefix.return_value = "memory"

        hits = [MagicMock(file_path=f"memory/f{i}.md", content=f"c{i}", score=1.0 - i * 0.1) for i in range(5)]
        mock_search.return_value = hits

        req = MemorySearchRequest(query="test", top_k=2)
        result = await search_memory(req, auth=MagicMock())

        assert len(result.results) == 2
