"""Tests for ENCRYPTION_KEY enforcement at startup."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestHasEncryptedSecrets:
    @pytest.mark.asyncio
    async def test_no_providers_returns_false(self):
        from app.services.providers import has_encrypted_secrets

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.providers.async_session", return_value=mock_db):
            assert await has_encrypted_secrets() is False

    @pytest.mark.asyncio
    async def test_plaintext_key_returns_false(self):
        from app.services.providers import has_encrypted_secrets

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [("sk-plaintext-key-123", None)]
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.providers.async_session", return_value=mock_db):
            assert await has_encrypted_secrets() is False

    @pytest.mark.asyncio
    async def test_encrypted_api_key_returns_true(self):
        from app.services.providers import has_encrypted_secrets

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [("enc:gAAAAA_encrypted_data_here", None)]
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.providers.async_session", return_value=mock_db):
            assert await has_encrypted_secrets() is True

    @pytest.mark.asyncio
    async def test_encrypted_management_key_returns_true(self):
        from app.services.providers import has_encrypted_secrets

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [
            ("sk-plain-api-key", {"management_key": "enc:gAAAAA_encrypted"})
        ]
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.providers.async_session", return_value=mock_db):
            assert await has_encrypted_secrets() is True

    @pytest.mark.asyncio
    async def test_none_api_key_returns_false(self):
        from app.services.providers import has_encrypted_secrets

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = [(None, {})]
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.execute = AsyncMock(return_value=mock_result)

        with patch("app.services.providers.async_session", return_value=mock_db):
            assert await has_encrypted_secrets() is False
