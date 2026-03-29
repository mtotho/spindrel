"""Tests for app.services.memory_search — hybrid memory search."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.bots import (
    BotConfig, KnowledgeConfig, MemoryConfig,
    WorkspaceConfig, WorkspaceIndexingConfig,
)
from app.services.memory_search import hybrid_memory_search


def _bot(
    bot_id="test_bot",
    memory_scheme="workspace-files",
    embedding_model=None,
    _workspace_raw=None,
    _ws_indexing_config=None,
) -> BotConfig:
    ws = WorkspaceConfig(
        enabled=True,
        indexing=WorkspaceIndexingConfig(enabled=False, embedding_model=embedding_model),
    )
    return BotConfig(
        id=bot_id, name="Test", model="gpt-4", system_prompt="You are helpful.",
        memory=MemoryConfig(), knowledge=KnowledgeConfig(),
        memory_scheme=memory_scheme,
        workspace=ws,
        _workspace_raw=_workspace_raw or {},
        _ws_indexing_config=_ws_indexing_config,
    )


class TestHybridMemorySearchSignature:
    """Test that the new roots/embedding_model parameters work correctly."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self):
        result = await hybrid_memory_search(query="   ", bot_id="bot", roots=["/ws"])
        assert result == []

    @pytest.mark.asyncio
    async def test_no_roots_returns_empty(self):
        result = await hybrid_memory_search(query="test", bot_id="bot")
        assert result == []

    @pytest.mark.asyncio
    async def test_single_root_backward_compat(self):
        """The deprecated `root` param should still work."""
        mock_embed = AsyncMock(return_value=[0.1] * 256)
        mock_session = MagicMock()
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.memory_search.embed_text", mock_embed),
            patch("app.services.memory_search.async_session", mock_session),
        ):
            result = await hybrid_memory_search(
                query="test query",
                bot_id="bot",
                root="/ws/bot",
            )

        assert result == []
        # Should use default model (no model= kwarg passed)
        mock_embed.assert_called_once_with("test query", model=None)

    @pytest.mark.asyncio
    async def test_embedding_model_passed_to_embed_text(self):
        """When embedding_model is specified, it should be forwarded to embed_text."""
        mock_embed = AsyncMock(return_value=[0.1] * 256)
        mock_session = MagicMock()
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.memory_search.embed_text", mock_embed),
            patch("app.services.memory_search.async_session", mock_session),
        ):
            result = await hybrid_memory_search(
                query="test query",
                bot_id="bot",
                roots=["/ws/bot"],
                embedding_model="custom/embed-v2",
            )

        assert result == []
        mock_embed.assert_called_once_with("test query", model="custom/embed-v2")

    @pytest.mark.asyncio
    async def test_multiple_roots_generates_in_clause(self):
        """When multiple roots are provided, SQL should use IN clause."""
        mock_embed = AsyncMock(return_value=[0.1] * 256)
        mock_session = MagicMock()
        mock_db = AsyncMock()
        executed_sql = {}

        async def capture_execute(sql, params):
            executed_sql["sql"] = str(sql)
            executed_sql["params"] = params
            return MagicMock(all=MagicMock(return_value=[]))

        mock_db.execute = capture_execute
        mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.memory_search.embed_text", mock_embed),
            patch("app.services.memory_search.async_session", mock_session),
        ):
            await hybrid_memory_search(
                query="test",
                bot_id="bot",
                roots=["/ws/root1", "/ws/root2", "/ws/root3"],
            )

        # Check that all roots are passed as params
        assert executed_sql["params"]["root_0"] == "/ws/root1"
        assert executed_sql["params"]["root_1"] == "/ws/root2"
        assert executed_sql["params"]["root_2"] == "/ws/root3"

    @pytest.mark.asyncio
    async def test_embed_failure_returns_empty(self):
        """If embed_text raises, should return [] gracefully."""
        mock_embed = AsyncMock(side_effect=RuntimeError("API down"))

        with patch("app.services.memory_search.embed_text", mock_embed):
            result = await hybrid_memory_search(
                query="test", bot_id="bot", roots=["/ws"],
            )

        assert result == []


class TestSearchMemoryResolvesModel:
    """Integration-level test: search_memory resolves embedding model from bot config."""

    @pytest.mark.asyncio
    async def test_search_memory_passes_resolved_model(self):
        """search_memory should resolve the embedding model via resolve_indexing and pass it."""
        from app.tools.local.memory_files import search_memory

        bot = _bot(
            bot_id="my_bot",
            embedding_model="custom/model",
            _workspace_raw={"indexing": {"embedding_model": "custom/model"}},
        )

        mock_search = AsyncMock(return_value=[])

        with (
            patch("app.tools.local.memory_files._get_bot_and_root", return_value=(bot, "my_bot", "/ws/my_bot")),
            patch("app.services.memory_search.hybrid_memory_search", mock_search),
            patch("app.services.workspace_indexing.get_all_roots", return_value=["/ws/my_bot"]),
        ):
            result = await search_memory("test query")

        assert "No matching memory content found." in result
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args
        assert call_kwargs.kwargs.get("embedding_model") == "custom/model"
        assert call_kwargs.kwargs.get("top_k") == 10
        # Should pass roots as list, not single root
        assert "roots" in call_kwargs.kwargs or len(call_kwargs.args) >= 3
