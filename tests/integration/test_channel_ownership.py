"""Integration tests for channel ownership (private/user_id) and visibility filtering."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from unittest.mock import patch

from app.db.models import Channel, User
from app.services.channels import apply_channel_visibility, get_or_create_channel, resolve_integration_user
from sqlalchemy import select
from tests.integration.conftest import AUTH_HEADERS


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_user(db, *, email=None, is_admin=False, integration_config=None):
    user = User(
        id=uuid.uuid4(),
        email=email or f"user-{uuid.uuid4().hex[:8]}@test.com",
        display_name="Test User",
        auth_method="local",
        password_hash="fakehash",
        is_admin=is_admin,
        integration_config=integration_config or {},
    )
    db.add(user)
    await db.flush()
    return user


async def _create_channel_row(db, *, private=False, user_id=None, name=None, bot_id="test-bot"):
    ch = Channel(
        id=uuid.uuid4(),
        name=name or f"ch-{uuid.uuid4().hex[:8]}",
        bot_id=bot_id,
        client_id=f"client-{uuid.uuid4().hex[:8]}",
        private=private,
        user_id=user_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(ch)
    await db.flush()
    return ch


# ---------------------------------------------------------------------------
# get_or_create_channel — user_id / private params
# ---------------------------------------------------------------------------

class TestGetOrCreateChannelOwnership:
    async def test_creates_channel_with_user_id(self, db_session):
        user = await _create_user(db_session)
        ch = await get_or_create_channel(
            db_session,
            client_id=f"owned-{uuid.uuid4().hex[:8]}",
            bot_id="test-bot",
            user_id=user.id,
            private=True,
        )
        assert ch.user_id == user.id
        assert ch.private is True

    async def test_creates_public_channel_by_default(self, db_session):
        ch = await get_or_create_channel(
            db_session,
            client_id=f"public-{uuid.uuid4().hex[:8]}",
            bot_id="test-bot",
        )
        assert ch.private is False
        assert ch.user_id is None

    async def test_anonymous_channel_with_user(self, db_session):
        """Channel created without client_id still gets user_id/private."""
        user = await _create_user(db_session)
        ch = await get_or_create_channel(
            db_session,
            bot_id="test-bot",
            user_id=user.id,
            private=True,
        )
        assert ch.user_id == user.id
        assert ch.private is True

    async def test_existing_channel_not_modified(self, db_session):
        """get_or_create on existing channel doesn't overwrite user_id/private."""
        user = await _create_user(db_session)
        client_id = f"existing-{uuid.uuid4().hex[:8]}"

        ch1 = await get_or_create_channel(
            db_session,
            client_id=client_id,
            bot_id="test-bot",
        )
        assert ch1.private is False

        # Second call with different private/user_id — should not change
        ch2 = await get_or_create_channel(
            db_session,
            client_id=client_id,
            bot_id="test-bot",
            user_id=user.id,
            private=True,
        )
        assert ch2.id == ch1.id
        # Original values preserved (existing channel found by client_id)
        assert ch2.private is False
        assert ch2.user_id is None


# ---------------------------------------------------------------------------
# apply_channel_visibility
# ---------------------------------------------------------------------------

class TestApplyChannelVisibility:
    async def test_api_key_sees_all(self, db_session):
        """String auth result (API key) sees all channels."""
        user = await _create_user(db_session)
        await _create_channel_row(db_session, private=True, user_id=user.id)
        await _create_channel_row(db_session, private=False)
        await _create_channel_row(db_session, private=True)  # no user_id
        await db_session.commit()

        stmt = select(Channel)
        stmt = apply_channel_visibility(stmt, "test-key")
        result = (await db_session.execute(stmt)).scalars().all()
        assert len(result) == 3

    async def test_admin_sees_all(self, db_session):
        admin = await _create_user(db_session, is_admin=True)
        other = await _create_user(db_session)
        await _create_channel_row(db_session, private=True, user_id=other.id)
        await _create_channel_row(db_session, private=False)
        await db_session.commit()

        stmt = select(Channel)
        stmt = apply_channel_visibility(stmt, admin)
        result = (await db_session.execute(stmt)).scalars().all()
        assert len(result) == 2

    async def test_regular_user_sees_own_private_and_public(self, db_session):
        user_a = await _create_user(db_session)
        user_b = await _create_user(db_session)

        ch_public = await _create_channel_row(db_session, private=False)
        ch_a_private = await _create_channel_row(db_session, private=True, user_id=user_a.id)
        ch_b_private = await _create_channel_row(db_session, private=True, user_id=user_b.id)
        await db_session.commit()

        # User A sees: public + own private
        stmt = apply_channel_visibility(select(Channel), user_a)
        result_a = (await db_session.execute(stmt)).scalars().all()
        result_a_ids = {ch.id for ch in result_a}
        assert ch_public.id in result_a_ids
        assert ch_a_private.id in result_a_ids
        assert ch_b_private.id not in result_a_ids

        # User B sees: public + own private
        stmt = apply_channel_visibility(select(Channel), user_b)
        result_b = (await db_session.execute(stmt)).scalars().all()
        result_b_ids = {ch.id for ch in result_b}
        assert ch_public.id in result_b_ids
        assert ch_b_private.id in result_b_ids
        assert ch_a_private.id not in result_b_ids

    async def test_none_user_sees_all(self, db_session):
        await _create_channel_row(db_session, private=True)
        await _create_channel_row(db_session, private=False)
        await db_session.commit()

        stmt = apply_channel_visibility(select(Channel), None)
        result = (await db_session.execute(stmt)).scalars().all()
        assert len(result) == 2


# ---------------------------------------------------------------------------
# resolve_integration_user
# ---------------------------------------------------------------------------

class TestResolveIntegrationUser:
    async def test_finds_user_by_slack_id(self, db_session):
        user = await _create_user(
            db_session,
            integration_config={"slack": {"user_id": "U12345ABC"}},
        )
        await db_session.commit()

        found = await resolve_integration_user(db_session, "slack", "U12345ABC")
        assert found is not None
        assert found.id == user.id

    async def test_returns_none_for_unknown_slack_id(self, db_session):
        await _create_user(
            db_session,
            integration_config={"slack": {"user_id": "U12345ABC"}},
        )
        await db_session.commit()

        found = await resolve_integration_user(db_session, "slack", "UUNKNOWN")
        assert found is None

    async def test_returns_none_for_no_integration_config(self, db_session):
        await _create_user(db_session)
        await db_session.commit()

        found = await resolve_integration_user(db_session, "slack", "U12345ABC")
        assert found is None

    async def test_skips_inactive_users(self, db_session):
        user = await _create_user(
            db_session,
            integration_config={"slack": {"user_id": "UINACTIVE"}},
        )
        user.is_active = False
        await db_session.commit()

        found = await resolve_integration_user(db_session, "slack", "UINACTIVE")
        assert found is None


# ---------------------------------------------------------------------------
# API endpoints — ChannelOut includes private/user_id fields
# ---------------------------------------------------------------------------

class TestChannelOutSchema:
    async def test_create_channel_returns_private_field(self, client):
        resp = await client.post(
            "/api/v1/channels",
            json={"bot_id": "test-bot", "client_id": f"schema-{uuid.uuid4().hex[:8]}"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "private" in body
        assert body["private"] is False
        assert "user_id" in body

    async def test_create_channel_honors_body_user_id_for_admin_key(self, client, db_session):
        """Admin-scoped API key callers may pre-assign owner via body.user_id.
        Phase 3 UI new-channel wizard uses this to let admins reassign on create.
        """
        user = await _create_user(db_session)
        await db_session.commit()
        resp = await client.post(
            "/api/v1/channels",
            json={
                "bot_id": "test-bot",
                "client_id": f"owner-assign-{uuid.uuid4().hex[:8]}",
                "user_id": str(user.id),
                "private": True,
            },
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["user_id"] == str(user.id)
        assert body["private"] is True

    async def test_create_channel_rejects_invalid_user_id(self, client):
        resp = await client.post(
            "/api/v1/channels",
            json={
                "bot_id": "test-bot",
                "client_id": f"owner-bad-{uuid.uuid4().hex[:8]}",
                "user_id": "not-a-uuid",
            },
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 400

    async def test_list_channels_returns_private_field(self, client):
        await client.post(
            "/api/v1/channels",
            json={"bot_id": "test-bot", "client_id": f"schema-list-{uuid.uuid4().hex[:8]}"},
            headers=AUTH_HEADERS,
        )
        resp = await client.get("/api/v1/channels", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        for ch in resp.json():
            assert "private" in ch


# ---------------------------------------------------------------------------
# Admin channels-enriched visibility
# ---------------------------------------------------------------------------

class TestAdminChannelsVisibility:
    async def test_admin_channels_list_returns_ok(self, client):
        """Verify admin channel endpoints work with verify_auth_or_user."""
        resp = await client.get("/api/v1/admin/channels", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert "channels" in body
        assert "total" in body

    async def test_admin_channels_enriched_returns_ok(self, client):
        resp = await client.get("/api/v1/admin/channels-enriched", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert "channels" in body

    async def test_admin_channels_enriched_exposes_last_message_at(self, client, db_session):
        """HomeGrid tiles rely on last_message_at to show last-activity pills."""
        from app.db.models import Session as SessionRow
        ch = await _create_channel_row(db_session)
        last = datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc)
        db_session.add(SessionRow(
            id=uuid.uuid4(),
            client_id=ch.client_id,
            bot_id=ch.bot_id,
            channel_id=ch.id,
            created_at=last,
            last_active=last,
        ))
        await db_session.commit()

        resp = await client.get("/api/v1/admin/channels-enriched", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        rows = {row["id"]: row for row in resp.json()["channels"]}
        row = rows.get(str(ch.id))
        assert row is not None
        assert row["last_message_at"] is not None
        assert row["last_message_at"].startswith("2026-04-01T12:00")

    async def test_admin_channels_enriched_last_message_at_null_for_new_channel(self, client, db_session):
        ch = await _create_channel_row(db_session)
        await db_session.commit()
        resp = await client.get("/api/v1/admin/channels-enriched", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        rows = {row["id"]: row for row in resp.json()["channels"]}
        row = rows.get(str(ch.id))
        assert row is not None
        assert row["last_message_at"] is None

    async def test_admin_channels_enriched_recent_count_and_preview(self, client, db_session):
        """Spatial canvas channel tile reads recent_message_count_24h and
        last_message_preview to surface activity. Old messages must NOT
        contribute to the count; the preview comes from the latest message."""
        from app.db.models import Session as SessionRow, Message
        ch = await _create_channel_row(db_session)
        sess_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        db_session.add(SessionRow(
            id=sess_id,
            client_id=ch.client_id,
            bot_id=ch.bot_id,
            channel_id=ch.id,
            created_at=now,
            last_active=now,
        ))
        # 3 recent + 1 stale (>24h ago) — only the recent ones count
        recents = [
            Message(id=uuid.uuid4(), session_id=sess_id, role="user", content="first user msg", created_at=now - timedelta(hours=2)),
            Message(id=uuid.uuid4(), session_id=sess_id, role="assistant", content="middle assistant msg", created_at=now - timedelta(hours=1)),
            Message(id=uuid.uuid4(), session_id=sess_id, role="user", content="hey want to grab\ndinner tonight?", created_at=now - timedelta(minutes=5)),
        ]
        for m in recents:
            db_session.add(m)
        db_session.add(Message(
            id=uuid.uuid4(), session_id=sess_id, role="user",
            content="ancient history", created_at=now - timedelta(hours=25),
        ))
        await db_session.commit()

        resp = await client.get("/api/v1/admin/channels-enriched", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        rows = {row["id"]: row for row in resp.json()["channels"]}
        row = rows.get(str(ch.id))
        assert row is not None
        assert row["recent_message_count_24h"] == 3
        # Preview is the latest message body, newlines collapsed to spaces.
        assert row["last_message_preview"] == "hey want to grab dinner tonight?"

    async def test_admin_channels_enriched_preview_truncates_long_content(self, client, db_session):
        from app.db.models import Session as SessionRow, Message
        ch = await _create_channel_row(db_session)
        sess_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        db_session.add(SessionRow(
            id=sess_id,
            client_id=ch.client_id,
            bot_id=ch.bot_id,
            channel_id=ch.id,
            created_at=now,
            last_active=now,
        ))
        long_body = "x" * 200
        db_session.add(Message(id=uuid.uuid4(), session_id=sess_id, role="user", content=long_body, created_at=now))
        await db_session.commit()

        resp = await client.get("/api/v1/admin/channels-enriched", headers=AUTH_HEADERS)
        rows = {row["id"]: row for row in resp.json()["channels"]}
        row = rows.get(str(ch.id))
        assert row is not None
        preview = row["last_message_preview"]
        assert preview is not None
        assert preview.endswith("…")
        # 80 leading characters + ellipsis (rstrip on truncation may drop
        # trailing content, but for an all-x body none is dropped).
        assert len(preview) == 81

    async def test_admin_channels_enriched_zero_count_and_null_preview_when_quiet(self, client, db_session):
        ch = await _create_channel_row(db_session)
        await db_session.commit()
        resp = await client.get("/api/v1/admin/channels-enriched", headers=AUTH_HEADERS)
        rows = {row["id"]: row for row in resp.json()["channels"]}
        row = rows.get(str(ch.id))
        assert row is not None
        assert row["recent_message_count_24h"] == 0
        assert row["last_message_preview"] is None


# Widget pin CRUD moved to /api/v1/widgets/dashboard (slug=channel:<uuid>) —
# see tests/unit/test_dashboard_pins_service.py for the direct coverage and
# tests/unit/test_dashboards_service.py for the channel-dashboard lifecycle.


# ---------------------------------------------------------------------------
# Phase 4 — Channel ownership enforcement on PUT/PATCH/DELETE + GET visibility
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def jwt_client_factory(engine, db_session):
    """Per-test client whose `verify_auth_or_user` returns a chosen User principal.

    Mirrors the `client_factory` shape in `test_widget_auth_mint.py`. Used to
    drive the JWT-as-non-admin paths that the default `client` fixture's
    static-key override hides.
    """
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession as _AS

    from app.dependencies import get_db, verify_auth_or_user
    from app.routers.api_v1 import router as api_v1_router

    _factory = async_sessionmaker(engine, class_=_AS, expire_on_commit=False)

    def _make(user: User):
        # Eagerly resolve scopes the way verify_auth_or_user would (Phase 1.5)
        # so require_scopes() doesn't fail closed for legitimate non-admins.
        # Tests pass a list explicitly via attach_scopes() below when relevant.
        if not hasattr(user, "_resolved_scopes"):
            user._resolved_scopes = ["chat", "channels:read", "channels:write"]
        app = FastAPI()
        app.include_router(api_v1_router)

        async def _override_get_db():
            yield db_session

        async def _override_auth():
            return user

        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[verify_auth_or_user] = _override_auth

        transport = ASGITransport(app=app)
        return AsyncClient(transport=transport, base_url="http://test")

    yield _make


def _attach_scopes(user: User, scopes: list[str]) -> User:
    user._resolved_scopes = list(scopes)
    return user


class TestChannelOwnershipEnforcement:
    async def test_owner_can_update_own_channel(self, jwt_client_factory, db_session):
        owner = await _create_user(db_session)
        ch = await _create_channel_row(db_session, user_id=owner.id)
        await db_session.commit()

        async with jwt_client_factory(owner) as ac:
            resp = await ac.put(
                f"/api/v1/channels/{ch.id}",
                json={"name": "renamed-by-owner"},
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "renamed-by-owner"

    async def test_non_owner_cannot_update_channel(self, jwt_client_factory, db_session):
        owner = await _create_user(db_session)
        intruder = await _create_user(db_session)
        ch = await _create_channel_row(db_session, user_id=owner.id)
        await db_session.commit()

        async with jwt_client_factory(intruder) as ac:
            resp = await ac.put(
                f"/api/v1/channels/{ch.id}",
                json={"name": "hijacked"},
            )
        assert resp.status_code == 403
        assert "owner" in resp.json()["detail"].lower()

    async def test_non_owner_cannot_delete_channel(self, jwt_client_factory, db_session):
        owner = await _create_user(db_session)
        intruder = await _create_user(db_session)
        ch = await _create_channel_row(db_session, user_id=owner.id)
        await db_session.commit()

        async with jwt_client_factory(intruder) as ac:
            resp = await ac.delete(f"/api/v1/channels/{ch.id}")
        assert resp.status_code == 403

        # Channel still exists
        await db_session.refresh(ch)
        assert ch.id is not None

    async def test_owner_can_delete_own_channel(self, jwt_client_factory, db_session):
        owner = await _create_user(db_session)
        ch = await _create_channel_row(db_session, user_id=owner.id)
        await db_session.commit()

        async with jwt_client_factory(owner) as ac:
            resp = await ac.delete(f"/api/v1/channels/{ch.id}")
        assert resp.status_code == 204

        # Channel is gone
        result = await db_session.execute(select(Channel).where(Channel.id == ch.id))
        assert result.scalar_one_or_none() is None

    async def test_admin_can_update_any_channel(self, jwt_client_factory, db_session):
        owner = await _create_user(db_session)
        admin = await _create_user(db_session, is_admin=True)
        ch = await _create_channel_row(db_session, user_id=owner.id)
        await db_session.commit()

        async with jwt_client_factory(admin) as ac:
            resp = await ac.put(
                f"/api/v1/channels/{ch.id}",
                json={"name": "admin-rename"},
            )
        assert resp.status_code == 200, resp.text

    async def test_admin_can_delete_any_channel(self, jwt_client_factory, db_session):
        owner = await _create_user(db_session)
        admin = await _create_user(db_session, is_admin=True)
        ch = await _create_channel_row(db_session, user_id=owner.id)
        await db_session.commit()

        async with jwt_client_factory(admin) as ac:
            resp = await ac.delete(f"/api/v1/channels/{ch.id}")
        assert resp.status_code == 204

    async def test_unowned_channel_rejects_non_admin_edit(self, jwt_client_factory, db_session):
        """Legacy/orphaned channels (user_id=NULL) must require admin to edit."""
        anyone = await _create_user(db_session)
        ch = await _create_channel_row(db_session, user_id=None)
        await db_session.commit()

        async with jwt_client_factory(anyone) as ac:
            resp = await ac.put(
                f"/api/v1/channels/{ch.id}",
                json={"name": "claimed"},
            )
        assert resp.status_code == 403

    async def test_non_owner_cannot_update_config(self, jwt_client_factory, db_session):
        owner = await _create_user(db_session)
        intruder = await _create_user(db_session)
        ch = await _create_channel_row(db_session, user_id=owner.id)
        await db_session.commit()

        async with jwt_client_factory(intruder) as ac:
            resp = await ac.patch(
                f"/api/v1/channels/{ch.id}/config",
                json={"max_iterations": 99},
            )
        assert resp.status_code == 403


class TestChannelGetVisibility:
    async def test_non_admin_cannot_get_other_users_private_channel(
        self, jwt_client_factory, db_session,
    ):
        owner = await _create_user(db_session)
        intruder = await _create_user(db_session)
        ch = await _create_channel_row(db_session, private=True, user_id=owner.id)
        await db_session.commit()

        async with jwt_client_factory(intruder) as ac:
            resp = await ac.get(f"/api/v1/channels/{ch.id}")
        # 404 (not 403) — don't leak the channel's existence
        assert resp.status_code == 404

    async def test_owner_can_get_own_private_channel(self, jwt_client_factory, db_session):
        owner = await _create_user(db_session)
        ch = await _create_channel_row(db_session, private=True, user_id=owner.id)
        await db_session.commit()

        async with jwt_client_factory(owner) as ac:
            resp = await ac.get(f"/api/v1/channels/{ch.id}")
        assert resp.status_code == 200
        assert resp.json()["private"] is True

    async def test_non_owner_can_get_public_channel(self, jwt_client_factory, db_session):
        owner = await _create_user(db_session)
        viewer = await _create_user(db_session)
        ch = await _create_channel_row(db_session, private=False, user_id=owner.id)
        await db_session.commit()

        async with jwt_client_factory(viewer) as ac:
            resp = await ac.get(f"/api/v1/channels/{ch.id}")
        assert resp.status_code == 200

    async def test_admin_can_get_any_private_channel(self, jwt_client_factory, db_session):
        owner = await _create_user(db_session)
        admin = await _create_user(db_session, is_admin=True)
        ch = await _create_channel_row(db_session, private=True, user_id=owner.id)
        await db_session.commit()

        async with jwt_client_factory(admin) as ac:
            resp = await ac.get(f"/api/v1/channels/{ch.id}")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Phase 6 — Integration binding lockdown
#
# ``member_user`` preset grants ``channels:write``, and ``has_scope`` covers
# ``channels.integrations:write`` via parent-covers-child. That leaks binding
# mutation to non-admins despite the Phase 0 decision ("admin-only"). The
# ``require_admin_and_scope`` dependency now enforces admin-ness on top of
# the scope check for the 6 binding write endpoints. These pins fail if the
# parent-cover leak reopens.
# ---------------------------------------------------------------------------
class TestChannelIntegrationBindingAdminGate:
    async def test_non_admin_cannot_bind_integration(self, jwt_client_factory, db_session):
        member = await _create_user(db_session)
        ch = await _create_channel_row(db_session, user_id=member.id)
        await db_session.commit()

        async with jwt_client_factory(member) as ac:
            resp = await ac.post(
                f"/api/v1/channels/{ch.id}/integrations",
                json={
                    "integration_type": "slack",
                    "client_id": "slack:C123",
                },
            )
        assert resp.status_code == 403
        assert "admin" in resp.json()["detail"].lower()

    async def test_non_admin_cannot_unbind_integration(self, jwt_client_factory, db_session):
        from app.db.models import ChannelIntegration

        member = await _create_user(db_session)
        ch = await _create_channel_row(db_session, user_id=member.id)
        binding = ChannelIntegration(
            channel_id=ch.id,
            integration_type="slack",
            client_id=f"slack:{uuid.uuid4().hex[:8]}",
            activated=True,
        )
        db_session.add(binding)
        await db_session.commit()

        async with jwt_client_factory(member) as ac:
            resp = await ac.delete(
                f"/api/v1/channels/{ch.id}/integrations/{binding.id}",
            )
        assert resp.status_code == 403

    async def test_non_admin_cannot_adopt_integration(self, jwt_client_factory, db_session):
        from app.db.models import ChannelIntegration

        member = await _create_user(db_session)
        ch1 = await _create_channel_row(db_session, user_id=member.id)
        ch2 = await _create_channel_row(db_session, user_id=member.id)
        binding = ChannelIntegration(
            channel_id=ch1.id,
            integration_type="slack",
            client_id=f"slack:{uuid.uuid4().hex[:8]}",
            activated=True,
        )
        db_session.add(binding)
        await db_session.commit()

        async with jwt_client_factory(member) as ac:
            resp = await ac.post(
                f"/api/v1/channels/{ch1.id}/integrations/{binding.id}/adopt",
                json={"target_channel_id": str(ch2.id)},
            )
        assert resp.status_code == 403

    async def test_non_admin_cannot_activate_integration(self, jwt_client_factory, db_session):
        member = await _create_user(db_session)
        ch = await _create_channel_row(db_session, user_id=member.id)
        await db_session.commit()

        async with jwt_client_factory(member) as ac:
            resp = await ac.post(
                f"/api/v1/channels/{ch.id}/integrations/excalidraw/activate",
            )
        assert resp.status_code == 403

    async def test_non_admin_cannot_deactivate_integration(self, jwt_client_factory, db_session):
        member = await _create_user(db_session)
        ch = await _create_channel_row(db_session, user_id=member.id)
        await db_session.commit()

        async with jwt_client_factory(member) as ac:
            resp = await ac.post(
                f"/api/v1/channels/{ch.id}/integrations/excalidraw/deactivate",
            )
        assert resp.status_code == 403

    async def test_non_admin_cannot_update_activation_config(self, jwt_client_factory, db_session):
        member = await _create_user(db_session)
        ch = await _create_channel_row(db_session, user_id=member.id)
        await db_session.commit()

        async with jwt_client_factory(member) as ac:
            resp = await ac.patch(
                f"/api/v1/channels/{ch.id}/integrations/excalidraw/config",
                json={"config": {"whatever": "value"}},
            )
        assert resp.status_code == 403

    async def test_non_admin_can_list_bindings_readonly(self, jwt_client_factory, db_session):
        """Reads stay allowed — non-admins see bindings on their own channel."""
        member = await _create_user(db_session)
        ch = await _create_channel_row(db_session, user_id=member.id)
        await db_session.commit()

        async with jwt_client_factory(member) as ac:
            resp = await ac.get(f"/api/v1/channels/{ch.id}/integrations")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_admin_can_bind_integration(self, jwt_client_factory, db_session):
        """Admin JWT passes the admin-and-scope gate; endpoint returns 201."""
        admin = await _create_user(db_session, is_admin=True)
        ch = await _create_channel_row(db_session, user_id=None)
        await db_session.commit()

        async with jwt_client_factory(admin) as ac:
            resp = await ac.post(
                f"/api/v1/channels/{ch.id}/integrations",
                json={
                    "integration_type": "slack",
                    "client_id": f"slack:{uuid.uuid4().hex[:8]}",
                },
            )
        assert resp.status_code == 201, resp.text

    async def test_scoped_key_without_admin_is_rejected(
        self, engine, db_session,
    ):
        """ApiKeyAuth with channels:write but no ``admin`` scope is denied.

        Mirrors the ``slack_integration``/``chat_client`` preset shape — these
        keys carry ``channels:write`` and via parent-cover technically satisfy
        ``channels.integrations:write``. The admin gate must reject them.
        """
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from app.dependencies import ApiKeyAuth, get_db, verify_auth_or_user
        from app.routers.api_v1 import router as api_v1_router

        ch = await _create_channel_row(db_session, user_id=None)
        await db_session.commit()

        scoped_key = ApiKeyAuth(
            key_id=uuid.uuid4(),
            scopes=["chat", "channels:read", "channels:write"],
            name="slack-integration-style",
        )

        app = FastAPI()
        app.include_router(api_v1_router)

        async def _override_get_db():
            yield db_session

        async def _override_auth():
            return scoped_key

        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[verify_auth_or_user] = _override_auth

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/v1/channels/{ch.id}/integrations",
                json={
                    "integration_type": "slack",
                    "client_id": f"slack:{uuid.uuid4().hex[:8]}",
                },
            )
        assert resp.status_code == 403
        assert "admin" in resp.json()["detail"].lower()
