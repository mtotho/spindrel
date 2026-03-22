"""Priority 3 tests for app.agent.persona — get/write/edit/append persona (mocked DB)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


_SENTINEL = object()


def _mock_async_session(scalar_result=_SENTINEL):
    """Create a mock async_session context manager.

    scalar_result: value that db.execute(...).scalar_one_or_none() returns.
    Use _SENTINEL (default) to skip setting up execute.
    """
    db = AsyncMock()
    if scalar_result is not _SENTINEL:
        result = MagicMock()
        result.scalar_one_or_none.return_value = scalar_result
        db.execute = AsyncMock(return_value=result)

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=db)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm, db


class TestGetPersona:
    @pytest.mark.asyncio
    async def test_returns_persona_when_found(self):
        from app.agent.persona import get_persona

        row = MagicMock()
        row.persona_layer = "I am a helpful bot."
        cm, db = _mock_async_session(scalar_result=row)

        with patch("app.agent.persona.async_session", return_value=cm):
            result = await get_persona("test_bot")
            assert result == "I am a helpful bot."

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        from app.agent.persona import get_persona

        cm, db = _mock_async_session(scalar_result=None)

        with patch("app.agent.persona.async_session", return_value=cm):
            result = await get_persona("nonexistent")
            assert result is None


class TestWritePersona:
    @pytest.mark.asyncio
    async def test_success(self):
        from app.agent.persona import write_persona

        cm, db = _mock_async_session()
        db.merge = AsyncMock()

        with patch("app.agent.persona.async_session", return_value=cm):
            ok, err = await write_persona("bot1", "New persona content")
            assert ok is True
            assert err is None
            db.merge.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failure(self):
        from app.agent.persona import write_persona

        cm, db = _mock_async_session()
        db.merge = AsyncMock(side_effect=Exception("db error"))

        with patch("app.agent.persona.async_session", return_value=cm):
            ok, err = await write_persona("bot1", "content")
            assert ok is False
            assert "db error" in err


class TestEditPersona:
    @pytest.mark.asyncio
    async def test_successful_edit(self):
        from app.agent.persona import edit_persona

        row = MagicMock()
        row.persona_layer = "Hello world, I am friendly."
        cm, db = _mock_async_session(scalar_result=row)

        with patch("app.agent.persona.async_session", return_value=cm):
            ok, err = await edit_persona("bot1", "friendly", "helpful")
            assert ok is True
            assert err is None
            assert row.persona_layer == "Hello world, I am helpful."

    @pytest.mark.asyncio
    async def test_old_text_not_found(self):
        from app.agent.persona import edit_persona

        row = MagicMock()
        row.persona_layer = "Hello world."
        cm, db = _mock_async_session(scalar_result=row)

        with patch("app.agent.persona.async_session", return_value=cm):
            ok, err = await edit_persona("bot1", "nonexistent text", "new")
            assert ok is False
            assert "old_text not found" in err

    @pytest.mark.asyncio
    async def test_persona_not_found(self):
        from app.agent.persona import edit_persona

        cm, db = _mock_async_session(scalar_result=None)

        with patch("app.agent.persona.async_session", return_value=cm):
            ok, err = await edit_persona("bot1", "old", "new")
            assert ok is False
            assert "Persona not found" in err

    @pytest.mark.asyncio
    async def test_empty_persona_layer(self):
        from app.agent.persona import edit_persona

        row = MagicMock()
        row.persona_layer = None
        cm, db = _mock_async_session(scalar_result=row)

        with patch("app.agent.persona.async_session", return_value=cm):
            ok, err = await edit_persona("bot1", "old", "new")
            assert ok is False
            assert "Persona not found" in err


class TestAppendToPersona:
    @pytest.mark.asyncio
    async def test_successful_append(self):
        from app.agent.persona import append_to_persona

        row = MagicMock()
        row.persona_layer = "Base content."
        cm, db = _mock_async_session(scalar_result=row)

        with patch("app.agent.persona.async_session", return_value=cm):
            ok, err = await append_to_persona("bot1", " Extra.")
            assert ok is True
            assert err is None
            assert row.persona_layer == "Base content. Extra."

    @pytest.mark.asyncio
    async def test_empty_content(self):
        from app.agent.persona import append_to_persona

        ok, err = await append_to_persona("bot1", "   ")
        assert ok is False
        assert "No content" in err

    @pytest.mark.asyncio
    async def test_persona_not_found(self):
        from app.agent.persona import append_to_persona

        cm, db = _mock_async_session(scalar_result=None)

        with patch("app.agent.persona.async_session", return_value=cm):
            ok, err = await append_to_persona("bot1", "content")
            assert ok is False
            assert "not found" in err.lower()
