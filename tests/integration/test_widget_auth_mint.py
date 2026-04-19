"""Integration tests for ``POST /api/v1/widget-auth/mint``.

Covers:
- Admin caller → token issued, scopes copied from bot's API key.
- Non-owner user → 403.
- Owner user → token issued.
- Bot without api_key_id → 400 with hint.
- Issued JWT decodes back through ``verify_auth_or_user`` with widget kind
  and carries the bot's scopes intact (so ``require_scopes`` gates the
  widget's API calls against the bot, not the viewing user).
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.models import ApiKey, Bot, User
from tests.integration.conftest import _TEST_REGISTRY, _get_test_bot

pytestmark = pytest.mark.asyncio


async def _make_bot_with_key(db_session, scopes: list[str], *, owner_id: uuid.UUID | None = None):
    from app.services.api_keys import create_api_key

    key, _ = await create_api_key(
        db_session,
        name="bot-key",
        scopes=scopes,
        store_key_value=True,
    )
    bot = Bot(
        id=f"bot-{uuid.uuid4().hex[:8]}",
        name="Widget Bot",
        display_name="Widget Bot",
        model="test/model",
        system_prompt="",
        api_key_id=key.id,
        user_id=owner_id,
    )
    db_session.add(bot)
    await db_session.commit()
    await db_session.refresh(bot)
    return bot, key


async def _make_user(db_session, *, is_admin: bool = False) -> User:
    user = User(
        email=f"u-{uuid.uuid4().hex[:6]}@test",
        display_name="U",
        password_hash="x",
        auth_method="local",
        is_admin=is_admin,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def client_factory(db_session):
    """Yields a factory that builds a client with a chosen auth principal."""
    from fastapi import FastAPI
    from app.routers.api_v1 import router as api_v1_router
    from app.dependencies import get_db, verify_auth_or_user

    def _make(auth_principal):
        app = FastAPI()
        app.include_router(api_v1_router)

        async def _override_get_db():
            yield db_session

        async def _override_auth():
            return auth_principal

        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[verify_auth_or_user] = _override_auth
        return app

    yield _make


async def _post_mint(app, body: dict):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        return await ac.post("/api/v1/widget-auth/mint", json=body)


class TestMint:
    async def test_admin_user_can_mint_for_any_bot(self, client_factory, db_session):
        admin = await _make_user(db_session, is_admin=True)
        bot, _ = await _make_bot_with_key(
            db_session, ["channels:read", "chat"], owner_id=None
        )
        app = client_factory(admin)

        resp = await _post_mint(app, {"source_bot_id": bot.id})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["bot_id"] == bot.id
        assert set(body["scopes"]) == {"channels:read", "chat"}
        assert body["token"].count(".") == 2  # JWT
        assert body["expires_in"] == 900

    async def test_owner_user_can_mint_for_their_bot(self, client_factory, db_session):
        owner = await _make_user(db_session, is_admin=False)
        bot, _ = await _make_bot_with_key(
            db_session, ["chat"], owner_id=owner.id
        )
        app = client_factory(owner)

        resp = await _post_mint(app, {"source_bot_id": bot.id})
        assert resp.status_code == 200, resp.text
        assert resp.json()["bot_id"] == bot.id

    async def test_non_owner_non_admin_403(self, client_factory, db_session):
        owner = await _make_user(db_session, is_admin=False)
        other = await _make_user(db_session, is_admin=False)
        bot, _ = await _make_bot_with_key(
            db_session, ["chat"], owner_id=owner.id
        )
        app = client_factory(other)

        resp = await _post_mint(app, {"source_bot_id": bot.id})
        assert resp.status_code == 403

    async def test_bot_without_api_key_400(self, client_factory, db_session):
        admin = await _make_user(db_session, is_admin=True)
        bot = Bot(
            id=f"bot-{uuid.uuid4().hex[:8]}",
            name="No Key",
            model="test/model",
            system_prompt="",
            api_key_id=None,
        )
        db_session.add(bot)
        await db_session.commit()
        app = client_factory(admin)

        resp = await _post_mint(app, {"source_bot_id": bot.id})
        assert resp.status_code == 400
        assert "no API permissions" in resp.json()["detail"]

    async def test_missing_bot_404(self, client_factory, db_session):
        admin = await _make_user(db_session, is_admin=True)
        app = client_factory(admin)
        resp = await _post_mint(app, {"source_bot_id": "does-not-exist"})
        assert resp.status_code == 404


class TestWidgetTokenVerification:
    async def test_minted_token_round_trips_through_verify_auth(
        self, client_factory, db_session
    ):
        """The minted JWT must be accepted by ``verify_auth_or_user`` with the
        bot's scopes — that's what lets the widget call scoped endpoints."""
        import jwt as _jwt

        from app.services.auth import _jwt_secret  # test-only import

        admin = await _make_user(db_session, is_admin=True)
        bot, _ = await _make_bot_with_key(
            db_session, ["channels:read", "chat"]
        )
        app = client_factory(admin)
        mint_resp = await _post_mint(app, {"source_bot_id": bot.id})
        token = mint_resp.json()["token"]

        payload = _jwt.decode(token, _jwt_secret, algorithms=["HS256"])
        assert payload["kind"] == "widget"
        assert payload["bot_id"] == bot.id
        assert set(payload["scopes"]) == {"channels:read", "chat"}

        # Exercise verify_auth_or_user directly with the minted token.
        from fastapi import Header
        from app.dependencies import verify_auth_or_user, ApiKeyAuth

        auth = await verify_auth_or_user.__wrapped__(  # type: ignore[attr-defined]
            authorization=f"Bearer {token}", db=db_session,
        ) if hasattr(verify_auth_or_user, "__wrapped__") else None
        if auth is None:
            # verify_auth_or_user is a plain async function; call directly.
            auth = await verify_auth_or_user(
                authorization=f"Bearer {token}", db=db_session,
            )
        assert isinstance(auth, ApiKeyAuth)
        assert set(auth.scopes) == {"channels:read", "chat"}
        assert auth.name == f"widget:{bot.id}"

    async def test_widget_token_rejected_by_verify_admin_auth_cleanly(
        self, client_factory, db_session
    ):
        """A widget JWT whose ``sub`` is a bot id must NOT crash admin-router
        auth with ``ValueError: badly formed hexadecimal UUID string``.
        Regression: an HTML-widget iframe using ``window.spindrel.api`` to
        call ``/api/v1/admin/tasks`` was triggering 500s because
        ``verify_admin_auth`` did ``UUID(payload["sub"])`` unconditionally.
        """
        from fastapi import HTTPException

        from app.dependencies import verify_admin_auth

        admin = await _make_user(db_session, is_admin=True)
        bot, _ = await _make_bot_with_key(db_session, ["chat"])
        app = client_factory(admin)
        mint_resp = await _post_mint(app, {"source_bot_id": bot.id})
        token = mint_resp.json()["token"]

        with pytest.raises(HTTPException) as excinfo:
            await verify_admin_auth(
                authorization=f"Bearer {token}", db=db_session,
            )
        assert excinfo.value.status_code == 401
