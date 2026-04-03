"""Unit tests for manage_secret tool."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_session(db_mock):
    """Create a mock async context manager wrapping a db mock."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=db_mock)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


class TestListSecrets:
    @pytest.mark.asyncio
    async def test_list_returns_secrets(self):
        from app.tools.local.admin_secrets import manage_secret

        secrets = [
            {"name": "API_KEY", "description": "Test key", "has_value": True, "created_at": "2026-01-01T00:00:00"},
            {"name": "DB_PASSWORD", "description": "", "has_value": True, "created_at": "2026-01-02T00:00:00"},
        ]

        db = AsyncMock()
        with patch("app.tools.local.admin_secrets.async_session", return_value=_mock_session(db)):
            with patch("app.tools.local.admin_secrets.secret_values.list_secrets", new_callable=AsyncMock, return_value=secrets):
                result = await manage_secret(action="list")

        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["name"] == "API_KEY"
        assert parsed[1]["name"] == "DB_PASSWORD"


class TestCreateSecret:
    @pytest.mark.asyncio
    async def test_create_secret(self):
        from app.tools.local.admin_secrets import manage_secret

        created = {"id": "abc", "name": "MY_TOKEN", "description": "A token", "has_value": True, "created_by": "tool", "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"}

        db = AsyncMock()
        # No existing secret with that name
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=execute_result)

        with patch("app.tools.local.admin_secrets.async_session", return_value=_mock_session(db)):
            with patch("app.tools.local.admin_secrets.secret_values.create_secret", new_callable=AsyncMock, return_value=created) as mock_create:
                result = await manage_secret(action="create", name="MY_TOKEN", value="secret123", description="A token")

        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert parsed["name"] == "MY_TOKEN"

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        assert call_kwargs[1]["name"] == "MY_TOKEN"
        assert call_kwargs[1]["value"] == "secret123"
        assert call_kwargs[1]["description"] == "A token"
        assert call_kwargs[1]["created_by"] == "tool"

    @pytest.mark.asyncio
    async def test_create_missing_name(self):
        from app.tools.local.admin_secrets import manage_secret

        result = await manage_secret(action="create", value="secret123")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "name" in parsed["error"]

    @pytest.mark.asyncio
    async def test_create_missing_value(self):
        from app.tools.local.admin_secrets import manage_secret

        result = await manage_secret(action="create", name="MY_TOKEN")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "value" in parsed["error"]

    @pytest.mark.asyncio
    async def test_create_invalid_name(self):
        from app.tools.local.admin_secrets import manage_secret

        result = await manage_secret(action="create", name="my-bad-name", value="x")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "UPPER_SNAKE_CASE" in parsed["error"]

    @pytest.mark.asyncio
    async def test_create_invalid_name_starts_with_number(self):
        from app.tools.local.admin_secrets import manage_secret

        result = await manage_secret(action="create", name="3_BAD", value="x")
        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_create_duplicate_name(self):
        from app.tools.local.admin_secrets import manage_secret

        db = AsyncMock()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = MagicMock()  # existing row
        db.execute = AsyncMock(return_value=execute_result)

        with patch("app.tools.local.admin_secrets.async_session", return_value=_mock_session(db)):
            result = await manage_secret(action="create", name="MY_TOKEN", value="x")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "already exists" in parsed["error"]


class TestDeleteSecret:
    @pytest.mark.asyncio
    async def test_delete_by_name(self):
        from app.tools.local.admin_secrets import manage_secret
        import uuid

        secret_id = uuid.uuid4()
        row = MagicMock()
        row.id = secret_id
        row.name = "OLD_KEY"

        db = AsyncMock()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = row
        db.execute = AsyncMock(return_value=execute_result)

        with patch("app.tools.local.admin_secrets.async_session", return_value=_mock_session(db)):
            with patch("app.tools.local.admin_secrets.secret_values.delete_secret", new_callable=AsyncMock, return_value=True) as mock_delete:
                result = await manage_secret(action="delete", name="OLD_KEY")

        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert parsed["name"] == "OLD_KEY"
        mock_delete.assert_called_once_with(db, secret_id)

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        from app.tools.local.admin_secrets import manage_secret

        db = AsyncMock()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=execute_result)

        with patch("app.tools.local.admin_secrets.async_session", return_value=_mock_session(db)):
            result = await manage_secret(action="delete", name="NONEXISTENT")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "not found" in parsed["error"]

    @pytest.mark.asyncio
    async def test_delete_missing_name(self):
        from app.tools.local.admin_secrets import manage_secret

        result = await manage_secret(action="delete")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "name" in parsed["error"]


class TestUnknownAction:
    @pytest.mark.asyncio
    async def test_unknown_action(self):
        from app.tools.local.admin_secrets import manage_secret

        result = await manage_secret(action="update")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "Unknown action" in parsed["error"]
