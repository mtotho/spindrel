"""Integration test fixtures: test FastAPI app, mock bot registry.

DB compilers and the ``engine`` / ``db_session`` fixtures live in the
top-level ``tests/conftest.py`` so unit tests share the same machinery.
"""
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Text, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agent.bots import BotConfig, MemoryConfig
from app.db.models import Base
from app.dependencies import ApiKeyAuth, get_db, verify_auth, verify_admin_auth, verify_auth_or_user

# Re-export shared fixtures so legacy imports keep working.
from tests.conftest import engine, db_session  # noqa: F401

# ---------------------------------------------------------------------------
# Test bot configuration
# ---------------------------------------------------------------------------

TEST_BOT = BotConfig(
    id="test-bot",
    name="Test Bot",
    model="test/model",
    system_prompt="You are a test bot.",
    memory=MemoryConfig(enabled=False),
)

DEFAULT_BOT = BotConfig(
    id="default",
    name="Default Bot",
    model="test/default-model",
    system_prompt="You are the default bot.",
    memory=MemoryConfig(enabled=False),
)

_TEST_REGISTRY = {"test-bot": TEST_BOT, "default": DEFAULT_BOT}

AUTH_HEADERS = {"Authorization": "Bearer test-key"}


# NOTE: ``engine`` and ``db_session`` fixtures live in ``tests/conftest.py``.

# ---------------------------------------------------------------------------
# FastAPI test app (no lifespan — avoids migrations, bot loading, etc.)
# ---------------------------------------------------------------------------

def _build_test_app():
    """Build a minimal FastAPI app with only the routers under test."""
    from fastapi import FastAPI
    from app.domain.errors import install_domain_error_handler
    from app.routers.api_v1 import router as api_v1_router
    from app.routers.chat import router as chat_router

    test_app = FastAPI()
    install_domain_error_handler(test_app)
    test_app.include_router(api_v1_router)
    test_app.include_router(chat_router)
    return test_app


@pytest_asyncio.fixture
async def client(engine, db_session):
    app = _build_test_app()

    _admin_auth = ApiKeyAuth(
        key_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        scopes=["admin"],
        name="test",
    )

    # Build a session factory from the test engine so services that create their
    # own sessions (via async_session()) use the test DB instead of the real one.
    _test_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _override_get_db():
        yield db_session

    async def _override_verify_auth():
        return "test-key"

    async def _override_admin_auth():
        return _admin_auth

    async def _override_auth_or_user():
        return _admin_auth

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[verify_auth] = _override_verify_auth
    app.dependency_overrides[verify_admin_auth] = _override_admin_auth
    app.dependency_overrides[verify_auth_or_user] = _override_auth_or_user

    # Patch bot registry + get_bot to use test bots, and get_persona to return None.
    # Also patch async_session in services that create their own sessions.
    with (
        patch("app.agent.bots._registry", _TEST_REGISTRY),
        patch("app.agent.bots.get_bot", side_effect=_get_test_bot),
        patch("app.agent.persona.get_persona", return_value=None),
        patch("app.services.workflows.async_session", _test_session_factory),
        patch("app.services.workflow_executor.async_session", _test_session_factory),
        patch("app.services.bot_hooks.async_session", _test_session_factory),
        patch("app.services.attachments.async_session", _test_session_factory),
        patch("app.services.skill_enrollment.async_session", _test_session_factory),
        patch("app.services.tool_enrollment.async_session", _test_session_factory),
        patch("app.services.sandbox.async_session", _test_session_factory),
        patch("app.services.providers.async_session", _test_session_factory),
        patch("app.services.openai_oauth.async_session", _test_session_factory),
        patch("app.services.chat_late_input.async_session", _test_session_factory),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()


def _get_test_bot(bot_id: str) -> BotConfig:
    from fastapi import HTTPException
    bot = _TEST_REGISTRY.get(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=f"Unknown bot: {bot_id}")
    return bot
