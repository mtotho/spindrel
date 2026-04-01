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


# ---------------------------------------------------------------------------
# update_secret cache — rename, value change, rename+value
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_secret_rename_preserves_value():
    """Renaming a secret should move the cached value to the new name."""
    from app.services import secret_values

    secret_values._cache.clear()
    secret_values._cache["OLD_KEY"] = "the-value"

    mock_row = MagicMock()
    mock_row.name = "OLD_KEY"
    mock_row.value = "enc:data"
    mock_row.description = ""
    mock_row.created_by = None
    mock_row.created_at = MagicMock(isoformat=MagicMock(return_value="2026-01-01T00:00:00"))
    mock_row.updated_at = MagicMock(isoformat=MagicMock(return_value="2026-01-01T00:00:00"))
    mock_row.id = "abc123"

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=mock_row)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    # After "rename", the mock simulates the new name
    def apply_rename():
        mock_row.name = "NEW_KEY"
    mock_db.commit.side_effect = apply_rename

    import uuid
    with patch("app.services.secret_values._rebuild_registry", new_callable=AsyncMock):
        result = await secret_values.update_secret(mock_db, uuid.uuid4(), name="NEW_KEY")

    assert result is not None
    assert "OLD_KEY" not in secret_values._cache
    assert secret_values._cache.get("NEW_KEY") == "the-value"
    secret_values._cache.clear()


@pytest.mark.asyncio
async def test_update_secret_value_only():
    """Updating only the value should keep the same key name."""
    from app.services import secret_values

    secret_values._cache.clear()
    secret_values._cache["MY_KEY"] = "old-val"

    mock_row = MagicMock()
    mock_row.name = "MY_KEY"
    mock_row.value = "enc:data"
    mock_row.description = ""
    mock_row.created_by = None
    mock_row.created_at = MagicMock(isoformat=MagicMock(return_value="2026-01-01T00:00:00"))
    mock_row.updated_at = MagicMock(isoformat=MagicMock(return_value="2026-01-01T00:00:00"))
    mock_row.id = "abc123"

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=mock_row)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    import uuid
    with patch("app.services.secret_values._rebuild_registry", new_callable=AsyncMock):
        with patch("app.services.secret_values.encrypt", return_value="enc:new"):
            result = await secret_values.update_secret(mock_db, uuid.uuid4(), value="new-val")

    assert result is not None
    assert secret_values._cache["MY_KEY"] == "new-val"
    secret_values._cache.clear()


@pytest.mark.asyncio
async def test_update_secret_rename_and_value():
    """Updating both name and value should cache correctly."""
    from app.services import secret_values

    secret_values._cache.clear()
    secret_values._cache["OLD_KEY"] = "old-val"

    mock_row = MagicMock()
    mock_row.name = "OLD_KEY"
    mock_row.value = "enc:data"
    mock_row.description = ""
    mock_row.created_by = None
    mock_row.created_at = MagicMock(isoformat=MagicMock(return_value="2026-01-01T00:00:00"))
    mock_row.updated_at = MagicMock(isoformat=MagicMock(return_value="2026-01-01T00:00:00"))
    mock_row.id = "abc123"

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=mock_row)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()

    def apply_rename():
        mock_row.name = "NEW_KEY"
    mock_db.commit.side_effect = apply_rename

    import uuid
    with patch("app.services.secret_values._rebuild_registry", new_callable=AsyncMock):
        with patch("app.services.secret_values.encrypt", return_value="enc:new"):
            result = await secret_values.update_secret(mock_db, uuid.uuid4(), name="NEW_KEY", value="new-val")

    assert result is not None
    assert "OLD_KEY" not in secret_values._cache
    assert secret_values._cache["NEW_KEY"] == "new-val"
    secret_values._cache.clear()
