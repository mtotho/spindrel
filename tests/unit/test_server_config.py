"""Tests for app.services.server_config — global fallback models cache."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.mark.asyncio
async def test_get_global_fallback_models_returns_cached():
    """get_global_fallback_models returns the module-level cache."""
    from app.services import server_config
    original = server_config._global_fallback_models
    try:
        server_config._global_fallback_models = [{"model": "test-model"}]
        assert server_config.get_global_fallback_models() == [{"model": "test-model"}]
    finally:
        server_config._global_fallback_models = original


@pytest.mark.asyncio
async def test_load_server_config_from_db():
    """load_server_config loads from DB row."""
    from app.services import server_config
    original = server_config._global_fallback_models

    mock_row = MagicMock()
    mock_row.global_fallback_models = [{"model": "db-model", "provider_id": None}]

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_row

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    try:
        with patch("app.db.engine.async_session", return_value=mock_session_ctx):
            await server_config.load_server_config()
        assert server_config._global_fallback_models == [{"model": "db-model", "provider_id": None}]
    finally:
        server_config._global_fallback_models = original


@pytest.mark.asyncio
async def test_load_server_config_seeds_from_env():
    """When DB row is empty, seeds from LLM_FALLBACK_MODEL env setting."""
    from app.services import server_config
    original = server_config._global_fallback_models

    mock_row = MagicMock()
    mock_row.global_fallback_models = []

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_row

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_settings = MagicMock()
    mock_settings.LLM_FALLBACK_MODEL = "env-fallback"

    try:
        with patch("app.db.engine.async_session", return_value=mock_session_ctx), \
             patch("app.config.settings", mock_settings):
            await server_config.load_server_config()
        assert server_config._global_fallback_models == [
            {"model": "env-fallback", "provider_id": None}
        ]
    finally:
        server_config._global_fallback_models = original


@pytest.mark.asyncio
async def test_load_server_config_no_row_no_env():
    """When DB has no row and no env fallback, cache stays empty."""
    from app.services import server_config
    original = server_config._global_fallback_models

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_settings = MagicMock()
    mock_settings.LLM_FALLBACK_MODEL = ""

    try:
        with patch("app.db.engine.async_session", return_value=mock_session_ctx), \
             patch("app.config.settings", mock_settings):
            await server_config.load_server_config()
        assert server_config._global_fallback_models == []
    finally:
        server_config._global_fallback_models = original
