"""Integration tests for ``/api/v1/admin/bots/{id}/grants`` CRUD.

Admin creates / lists / deletes grants. Bulk-grant endpoint is what the
dashboard share drawer uses to fix "viewers can't use this bot" in one
click.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.models import Bot, BotGrant, User


pytestmark = pytest.mark.asyncio


async def _make_bot(db_session) -> Bot:
    bot = Bot(
        id=f"bot-{uuid.uuid4().hex[:8]}",
        name="Grant Test Bot",
        display_name="Grant Test Bot",
        model="test/model",
        system_prompt="",
    )
    db_session.add(bot)
    await db_session.commit()
    await db_session.refresh(bot)
    return bot


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
async def admin_client(db_session):
    """FastAPI client authenticated as the admin, with overrides for db +
    ``verify_admin_auth`` so the /admin/ router accepts the request."""
    from fastapi import FastAPI
    from app.routers.api_v1 import router as api_v1_router
    from app.dependencies import get_db, verify_admin_auth, verify_auth_or_user

    admin = await _make_user(db_session, is_admin=True)

    app = FastAPI()
    app.include_router(api_v1_router)

    async def _override_get_db():
        yield db_session

    async def _override_admin():
        return admin

    async def _override_auth():
        return admin

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[verify_admin_auth] = _override_admin
    app.dependency_overrides[verify_auth_or_user] = _override_auth

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, admin


class TestGrantsCrud:
    async def test_list_empty(self, admin_client, db_session):
        client, _ = admin_client
        bot = await _make_bot(db_session)
        resp = await client.get(f"/api/v1/admin/bots/{bot.id}/grants")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_create_and_list(self, admin_client, db_session):
        client, admin = admin_client
        bot = await _make_bot(db_session)
        user = await _make_user(db_session, is_admin=False)

        resp = await client.post(
            f"/api/v1/admin/bots/{bot.id}/grants",
            json={"user_id": str(user.id), "role": "view"},
        )
        assert resp.status_code == 201, resp.text
        created = resp.json()
        assert created["user_id"] == str(user.id)
        assert created["role"] == "view"
        assert created["granted_by"] == str(admin.id)

        listed = (await client.get(f"/api/v1/admin/bots/{bot.id}/grants")).json()
        assert len(listed) == 1
        assert listed[0]["user_id"] == str(user.id)
        assert listed[0]["user_email"] == user.email

    async def test_create_dup_is_409(self, admin_client, db_session):
        client, _ = admin_client
        bot = await _make_bot(db_session)
        user = await _make_user(db_session, is_admin=False)
        await client.post(
            f"/api/v1/admin/bots/{bot.id}/grants",
            json={"user_id": str(user.id), "role": "view"},
        )
        dup = await client.post(
            f"/api/v1/admin/bots/{bot.id}/grants",
            json={"user_id": str(user.id), "role": "view"},
        )
        assert dup.status_code == 409

    async def test_rejects_unknown_role(self, admin_client, db_session):
        client, _ = admin_client
        bot = await _make_bot(db_session)
        user = await _make_user(db_session, is_admin=False)
        resp = await client.post(
            f"/api/v1/admin/bots/{bot.id}/grants",
            json={"user_id": str(user.id), "role": "manage"},
        )
        assert resp.status_code == 422

    async def test_delete_ok(self, admin_client, db_session):
        client, _ = admin_client
        bot = await _make_bot(db_session)
        user = await _make_user(db_session, is_admin=False)
        await client.post(
            f"/api/v1/admin/bots/{bot.id}/grants",
            json={"user_id": str(user.id)},
        )
        resp = await client.delete(
            f"/api/v1/admin/bots/{bot.id}/grants/{user.id}"
        )
        assert resp.status_code == 204

        listed = (await client.get(f"/api/v1/admin/bots/{bot.id}/grants")).json()
        assert listed == []

    async def test_delete_missing_is_404(self, admin_client, db_session):
        client, _ = admin_client
        bot = await _make_bot(db_session)
        resp = await client.delete(
            f"/api/v1/admin/bots/{bot.id}/grants/{uuid.uuid4()}"
        )
        assert resp.status_code == 404

    async def test_create_unknown_bot_is_404(self, admin_client, db_session):
        client, _ = admin_client
        user = await _make_user(db_session, is_admin=False)
        resp = await client.post(
            "/api/v1/admin/bots/does-not-exist/grants",
            json={"user_id": str(user.id)},
        )
        assert resp.status_code == 404

    async def test_bulk_grant_creates_new_skips_existing(
        self, admin_client, db_session
    ):
        client, _ = admin_client
        bot = await _make_bot(db_session)
        u1 = await _make_user(db_session, is_admin=False)
        u2 = await _make_user(db_session, is_admin=False)
        u3 = await _make_user(db_session, is_admin=False)

        # u1 already has a grant; bulk should include u2 + u3 without error.
        await client.post(
            f"/api/v1/admin/bots/{bot.id}/grants",
            json={"user_id": str(u1.id)},
        )
        resp = await client.post(
            f"/api/v1/admin/bots/{bot.id}/grants/bulk",
            json={"user_ids": [str(u1.id), str(u2.id), str(u3.id)]},
        )
        assert resp.status_code == 200, resp.text
        returned = {row["user_id"] for row in resp.json()}
        assert returned == {str(u1.id), str(u2.id), str(u3.id)}

        # DB: exactly 3 rows for this bot.
        from sqlalchemy import select
        rows = (await db_session.execute(
            select(BotGrant).where(BotGrant.bot_id == bot.id)
        )).scalars().all()
        assert len(rows) == 3

    async def test_bulk_rejects_unknown_user(self, admin_client, db_session):
        client, _ = admin_client
        bot = await _make_bot(db_session)
        u1 = await _make_user(db_session, is_admin=False)
        resp = await client.post(
            f"/api/v1/admin/bots/{bot.id}/grants/bulk",
            json={"user_ids": [str(u1.id), str(uuid.uuid4())]},
        )
        assert resp.status_code == 404
