"""Tests for the channel `protected` flag enforcement."""
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from app.dependencies import ApiKeyAuth


# ---------------------------------------------------------------------------
# Unit tests for _check_protected helper
# ---------------------------------------------------------------------------

def _make_channel(protected: bool = False):
    """Create a minimal Channel-like object."""
    return SimpleNamespace(
        id=uuid4(),
        name="test-channel",
        protected=protected,
    )


def _admin_api_key():
    return ApiKeyAuth(
        key_id=UUID("00000000-0000-0000-0000-000000000000"),
        scopes=["admin"],
        name="static-env-key",
    )


def _scoped_api_key(*scopes: str):
    return ApiKeyAuth(
        key_id=uuid4(),
        scopes=list(scopes),
        name="bot-key",
    )


def _jwt_user():
    """Simulate a JWT user (not an ApiKeyAuth instance)."""
    return SimpleNamespace(
        id=uuid4(),
        email="user@test.com",
        is_admin=True,
    )


class TestCheckProtected:
    def test_unprotected_channel_allows_any_auth(self):
        from app.routers.api_v1_channels import _check_protected

        channel = _make_channel(protected=False)
        # All auth types should pass without error
        _check_protected(channel, _admin_api_key())
        _check_protected(channel, _scoped_api_key("channels.messages:write"))
        _check_protected(channel, _jwt_user())

    def test_protected_channel_allows_admin_api_key(self):
        from app.routers.api_v1_channels import _check_protected

        channel = _make_channel(protected=True)
        _check_protected(channel, _admin_api_key())  # should not raise

    def test_protected_channel_allows_jwt_user(self):
        from app.routers.api_v1_channels import _check_protected

        channel = _make_channel(protected=True)
        _check_protected(channel, _jwt_user())  # should not raise

    def test_protected_channel_blocks_scoped_api_key(self):
        from app.routers.api_v1_channels import _check_protected

        channel = _make_channel(protected=True)
        with pytest.raises(HTTPException) as exc_info:
            _check_protected(channel, _scoped_api_key("channels.messages:write"))
        assert exc_info.value.status_code == 403
        assert "Protected channel" in exc_info.value.detail

    def test_protected_channel_blocks_multi_scope_non_admin_key(self):
        from app.routers.api_v1_channels import _check_protected

        channel = _make_channel(protected=True)
        key = _scoped_api_key("channels.messages:write", "channels:read", "tasks:write")
        with pytest.raises(HTTPException) as exc_info:
            _check_protected(channel, key)
        assert exc_info.value.status_code == 403

    def test_protected_channel_allows_key_with_admin_scope(self):
        from app.routers.api_v1_channels import _check_protected

        channel = _make_channel(protected=True)
        key = _scoped_api_key("admin", "channels.messages:write")
        _check_protected(channel, key)  # should not raise


# ---------------------------------------------------------------------------
# Test orchestrator channel setup
# ---------------------------------------------------------------------------

class TestEnsureOrchestratorChannel:
    @pytest.mark.asyncio
    async def test_sets_protected_on_new_channel(self):
        """ensure_orchestrator_channel should set protected=True."""
        from unittest.mock import AsyncMock, patch, MagicMock

        mock_channel = SimpleNamespace(
            id=uuid4(),
            name="Orchestrator",
            private=True,
            protected=False,
            carapaces_extra=[],
            updated_at=None,
            bot_id="orchestrator",
        )

        mock_db = AsyncMock()

        with patch("app.agent.bots._registry", {"orchestrator": True}), \
             patch("app.services.channels.async_session") as mock_session_ctx, \
             patch("app.services.channels.get_or_create_channel", new_callable=AsyncMock, return_value=mock_channel), \
             patch("app.services.channels.ensure_active_session", new_callable=AsyncMock):
            # Set up context manager
            mock_db_instance = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db_instance)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            # Mock the ToolPolicyRule query
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = True  # rule exists
            mock_db_instance.execute = AsyncMock(return_value=mock_result)

            from app.services.channels import ensure_orchestrator_channel
            await ensure_orchestrator_channel()

            # The channel should have been marked as protected
            assert mock_channel.protected is True

    @pytest.mark.asyncio
    async def test_renames_legacy_home_label(self):
        """Channels still named 'Home' get renamed to 'Orchestrator'."""
        from unittest.mock import AsyncMock, patch, MagicMock

        mock_channel = SimpleNamespace(
            id=uuid4(),
            name="Home",
            private=True,
            protected=True,
            carapaces_extra=["orchestrator"],
            updated_at=None,
            bot_id="orchestrator",
        )

        with patch("app.agent.bots._registry", {"orchestrator": True}), \
             patch("app.services.channels.async_session") as mock_session_ctx, \
             patch("app.services.channels.get_or_create_channel", new_callable=AsyncMock, return_value=mock_channel), \
             patch("app.services.channels.ensure_active_session", new_callable=AsyncMock):
            mock_db_instance = AsyncMock()
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db_instance)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = True
            mock_db_instance.execute = AsyncMock(return_value=mock_result)

            from app.services.channels import ensure_orchestrator_channel
            await ensure_orchestrator_channel()

            assert mock_channel.name == "Orchestrator"
