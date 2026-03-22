"""Integration tests for app.agent.persona — CRUD operations with real DB."""
import os
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.integration.conftest import engine  # reuse engine fixture


@pytest_asyncio.fixture
async def persona_db(engine):
    """Provide an async_session factory backed by the test engine."""
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    with patch("app.agent.persona.async_session", factory):
        yield factory


class TestGetPersona:
    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, persona_db):
        from app.agent.persona import get_persona
        result = await get_persona("nonexistent-bot")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_persona_text(self, persona_db):
        from app.agent.persona import write_persona, get_persona
        await write_persona("bot-a", "I am friendly.")
        result = await get_persona("bot-a")
        assert result == "I am friendly."


class TestWritePersona:
    @pytest.mark.asyncio
    async def test_create_new(self, persona_db):
        from app.agent.persona import write_persona, get_persona
        ok, err = await write_persona("bot-new", "Hello persona")
        assert ok is True
        assert err is None
        assert await get_persona("bot-new") == "Hello persona"

    @pytest.mark.asyncio
    async def test_upsert_existing(self, persona_db):
        from app.agent.persona import write_persona, get_persona
        await write_persona("bot-up", "version 1")
        ok, err = await write_persona("bot-up", "version 2")
        assert ok is True
        assert await get_persona("bot-up") == "version 2"


class TestEditPersona:
    @pytest.mark.asyncio
    async def test_find_and_replace(self, persona_db):
        from app.agent.persona import write_persona, edit_persona, get_persona
        await write_persona("bot-edit", "I am a kind bot. I like cats.")
        ok, err = await edit_persona("bot-edit", "kind", "wise")
        assert ok is True
        assert err is None
        result = await get_persona("bot-edit")
        assert "wise" in result
        assert "kind" not in result

    @pytest.mark.asyncio
    async def test_old_text_not_found(self, persona_db):
        from app.agent.persona import write_persona, edit_persona
        await write_persona("bot-edit2", "I am a bot.")
        ok, err = await edit_persona("bot-edit2", "nonexistent text", "replacement")
        assert ok is False
        assert "old_text not found" in err

    @pytest.mark.asyncio
    async def test_persona_not_found(self, persona_db):
        from app.agent.persona import edit_persona
        ok, err = await edit_persona("no-such-bot", "a", "b")
        assert ok is False
        assert "Persona not found" in err


class TestAppendToPersona:
    @pytest.mark.asyncio
    async def test_append_to_existing(self, persona_db):
        from app.agent.persona import write_persona, append_to_persona, get_persona
        await write_persona("bot-app", "Base persona.")
        ok, err = await append_to_persona("bot-app", " Extra info.")
        assert ok is True
        assert err is None
        result = await get_persona("bot-app")
        assert result == "Base persona. Extra info."

    @pytest.mark.asyncio
    async def test_empty_content_rejected(self, persona_db):
        from app.agent.persona import append_to_persona
        ok, err = await append_to_persona("bot-app", "   ")
        assert ok is False
        assert "No content" in err

    @pytest.mark.asyncio
    async def test_persona_not_found(self, persona_db):
        from app.agent.persona import append_to_persona
        ok, err = await append_to_persona("missing-bot", "something")
        assert ok is False
        assert "not found" in err.lower()
