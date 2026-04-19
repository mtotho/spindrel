"""Integration tests for channel ownership (private/user_id) and visibility filtering."""
import uuid
from datetime import datetime, timezone

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


# Widget pin CRUD moved to /api/v1/widgets/dashboard (slug=channel:<uuid>) —
# see tests/unit/test_dashboard_pins_service.py for the direct coverage and
# tests/unit/test_dashboards_service.py for the channel-dashboard lifecycle.
