"""Tests for app.services.secret_values — encrypted env var vault."""
from __future__ import annotations

from unittest.mock import patch, MagicMock, AsyncMock
import pytest


# ---------------------------------------------------------------------------
# get_env_dict — returns cached plaintext values
# ---------------------------------------------------------------------------

def test_get_env_dict_empty():
    from app.services.secret_values import get_env_dict, _cache
    _cache.clear()
    assert get_env_dict() == {}


def test_get_env_dict_returns_copy():
    from app.services import secret_values
    secret_values._cache.clear()
    secret_values._cache["MY_KEY"] = "my-value"
    secret_values._cache["OTHER_KEY"] = "other-value"

    result = secret_values.get_env_dict()
    assert result == {"MY_KEY": "my-value", "OTHER_KEY": "other-value"}

    # Mutating the result shouldn't affect the cache
    result["MY_KEY"] = "changed"
    assert secret_values._cache["MY_KEY"] == "my-value"
    secret_values._cache.clear()


# ---------------------------------------------------------------------------
# load_from_db — decrypts values into cache
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_from_db():
    from app.services import secret_values

    mock_row = MagicMock()
    mock_row.name = "TEST_SECRET"
    mock_row.value = "enc:encrypted_data"

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_row]
    mock_result.scalars.return_value = mock_scalars
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("app.db.engine.async_session", return_value=mock_session):
        with patch("app.services.secret_values.decrypt", return_value="decrypted_value"):
            secret_values._cache.clear()
            await secret_values.load_from_db()
            assert secret_values._cache == {"TEST_SECRET": "decrypted_value"}
            secret_values._cache.clear()
