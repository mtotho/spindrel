"""Integration tests for /api/v1/sessions/scratch/* endpoints.

Cross-device scratch-session pointer: a user opening the same channel's
scratch chat from a second device should hit the SAME Session row the
first device is using (resolve-or-spawn). Reset archives the current one
and spawns a fresh row; list returns the caller's scratch history.
"""
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    Channel,
    Message,
    Session as SessionRow,
    User,
)
from app.dependencies import (
    ApiKeyAuth,
    get_db,
    verify_auth,
    verify_admin_auth,
    verify_auth_or_user,
)
from tests.integration.conftest import (
    AUTH_HEADERS,
    DEFAULT_BOT,
    TEST_BOT,
    _TEST_REGISTRY,
    _build_test_app,
    _get_test_bot,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def scratch_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"scratch-{uuid.uuid4().hex[:6]}@example.com",
        display_name="Scratch Tester",
        auth_method="local",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"other-{uuid.uuid4().hex[:6]}@example.com",
        display_name="Other Tester",
        auth_method="local",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_channel(db_session: AsyncSession) -> Channel:
    channel = Channel(
        id=uuid.uuid4(),
        client_id=f"scratch-ch-{uuid.uuid4().hex[:6]}",
        bot_id="test-bot",
        name="Scratch Test Channel",
    )
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(channel)
    return channel


@pytest_asyncio.fixture
async def user_client(engine, db_session, scratch_user):
    """FastAPI client whose auth resolves to a real User row (not an API key).

    Scratch endpoints require a User for ownership isolation; the shared
    ``client`` fixture returns an admin ApiKeyAuth which doesn't carry a
    user id.
    """
    app = _build_test_app()

    async def _override_get_db():
        yield db_session

    async def _override_verify_auth():
        return "test-key"

    _admin_auth = ApiKeyAuth(
        key_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        scopes=["admin", "chat"],
        name="test",
    )

    async def _override_admin_auth():
        return _admin_auth

    async def _override_auth_or_user():
        # Resolve as the user — require_scopes + User path.
        scratch_user._resolved_scopes = ["admin", "chat", "channels.messages:write"]
        return scratch_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[verify_auth] = _override_verify_auth
    app.dependency_overrides[verify_admin_auth] = _override_admin_auth
    app.dependency_overrides[verify_auth_or_user] = _override_auth_or_user

    _test_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    with (
        patch("app.agent.bots._registry", _TEST_REGISTRY),
        patch("app.agent.bots.get_bot", side_effect=_get_test_bot),
        patch("app.agent.persona.get_persona", return_value=None),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /api/v1/sessions/scratch/current
# ---------------------------------------------------------------------------


class TestCurrentScratchSession:
    async def test_spawns_on_first_call(self, user_client, db_session, test_channel, scratch_user):
        resp = await user_client.get(
            f"/api/v1/sessions/scratch/current",
            params={
                "parent_channel_id": str(test_channel.id),
                "bot_id": "test-bot",
            },
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        sid = uuid.UUID(body["session_id"])
        assert body["is_current"] is True
        assert body["parent_channel_id"] == str(test_channel.id)

        row = await db_session.get(SessionRow, sid)
        assert row is not None
        assert row.session_type == "ephemeral"
        assert row.parent_channel_id == test_channel.id
        assert row.owner_user_id == scratch_user.id
        assert row.is_current is True

    async def test_bootstraps_from_primary_summary(self, user_client, db_session, test_channel):
        primary_session = SessionRow(
            id=uuid.uuid4(),
            client_id=f"primary-{uuid.uuid4().hex[:6]}",
            bot_id="test-bot",
            channel_id=test_channel.id,
            title="Main thread",
            summary="Current primary summary",
        )
        db_session.add(primary_session)
        await db_session.flush()
        test_channel.active_session_id = primary_session.id
        await db_session.commit()

        resp = await user_client.get(
            "/api/v1/sessions/scratch/current",
            params={"parent_channel_id": str(test_channel.id), "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        scratch = await db_session.get(SessionRow, uuid.UUID(resp.json()["session_id"]))
        assert scratch is not None
        assert scratch.metadata_["bootstrap_source_session_id"] == str(primary_session.id)
        assert scratch.metadata_["bootstrap_source_title"] == "Main thread"
        assert scratch.metadata_["bootstrap_summary"] == "Current primary summary"

    async def test_idempotent_across_calls(self, user_client, test_channel):
        """Second call returns the same session_id (cross-device stability)."""
        params = {"parent_channel_id": str(test_channel.id), "bot_id": "test-bot"}
        r1 = await user_client.get("/api/v1/sessions/scratch/current", params=params, headers=AUTH_HEADERS)
        r2 = await user_client.get("/api/v1/sessions/scratch/current", params=params, headers=AUTH_HEADERS)
        assert r1.status_code == r2.status_code == 200
        assert r1.json()["session_id"] == r2.json()["session_id"]

    async def test_unknown_channel_404s(self, user_client):
        resp = await user_client.get(
            "/api/v1/sessions/scratch/current",
            params={"parent_channel_id": str(uuid.uuid4()), "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/sessions/scratch/reset
# ---------------------------------------------------------------------------


class TestResetScratchSession:
    async def test_reset_archives_old_and_spawns_new(
        self, user_client, db_session, test_channel
    ):
        params = {"parent_channel_id": str(test_channel.id), "bot_id": "test-bot"}
        # Establish a current scratch session.
        r1 = await user_client.get("/api/v1/sessions/scratch/current", params=params, headers=AUTH_HEADERS)
        old_sid = uuid.UUID(r1.json()["session_id"])

        # Reset it.
        r2 = await user_client.post(
            "/api/v1/sessions/scratch/reset",
            json={"parent_channel_id": str(test_channel.id), "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        assert r2.status_code == 201, r2.text
        new_sid = uuid.UUID(r2.json()["session_id"])
        assert new_sid != old_sid
        assert r2.json()["is_current"] is True

        # Old row still exists but is_current=False; new row is current.
        old_row = await db_session.get(SessionRow, old_sid)
        new_row = await db_session.get(SessionRow, new_sid)
        await db_session.refresh(old_row)
        await db_session.refresh(new_row)
        assert old_row is not None
        assert old_row.is_current is False
        assert new_row.is_current is True

    async def test_reset_does_not_delete_old_session(
        self, user_client, db_session, test_channel
    ):
        params = {"parent_channel_id": str(test_channel.id), "bot_id": "test-bot"}
        r1 = await user_client.get("/api/v1/sessions/scratch/current", params=params, headers=AUTH_HEADERS)
        old_sid = uuid.UUID(r1.json()["session_id"])
        await user_client.post(
            "/api/v1/sessions/scratch/reset",
            json={"parent_channel_id": str(test_channel.id), "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        still_there = await db_session.get(SessionRow, old_sid)
        assert still_there is not None


# ---------------------------------------------------------------------------
# GET /api/v1/sessions/scratch/list
# ---------------------------------------------------------------------------


class TestListScratchSessions:
    async def test_lists_newest_first_with_current_marker(
        self, user_client, db_session, test_channel
    ):
        params = {"parent_channel_id": str(test_channel.id), "bot_id": "test-bot"}
        r1 = await user_client.get("/api/v1/sessions/scratch/current", params=params, headers=AUTH_HEADERS)
        first_sid = r1.json()["session_id"]

        reset = await user_client.post(
            "/api/v1/sessions/scratch/reset",
            json={"parent_channel_id": str(test_channel.id), "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        second_sid = reset.json()["session_id"]

        resp = await user_client.get(
            "/api/v1/sessions/scratch/list",
            params={"parent_channel_id": str(test_channel.id)},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 2
        # Newest first — the freshly spawned second is on top and marked current.
        assert rows[0]["session_id"] == second_sid
        assert rows[0]["is_current"] is True
        assert rows[1]["session_id"] == first_sid
        assert rows[1]["is_current"] is False

    async def test_returns_title_summary_and_section_stats(
        self, user_client, db_session, test_channel
    ):
        params = {"parent_channel_id": str(test_channel.id), "bot_id": "test-bot"}
        current = await user_client.get("/api/v1/sessions/scratch/current", params=params, headers=AUTH_HEADERS)
        scratch_id = uuid.UUID(current.json()["session_id"])

        scratch = await db_session.get(SessionRow, scratch_id)
        assert scratch is not None
        scratch.title = "Named scratch"
        scratch.summary = "Short summary"
        db_session.add(Message(
            id=uuid.uuid4(),
            session_id=scratch_id,
            role="user",
            content="first message",
        ))
        from app.db.models import ConversationSection
        db_session.add(ConversationSection(
            id=uuid.uuid4(),
            channel_id=test_channel.id,
            session_id=scratch_id,
            sequence=1,
            title="Section 1",
            summary="Archived chunk",
            message_count=1,
            chunk_size=1,
        ))
        await db_session.commit()

        resp = await user_client.get(
            "/api/v1/sessions/scratch/list",
            params={"parent_channel_id": str(test_channel.id)},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        row = resp.json()[0]
        assert row["title"] == "Named scratch"
        assert row["summary"] == "Short summary"
        assert row["message_count"] == 1
        assert row["section_count"] == 1
        assert row["session_scope"] == "scratch"


class TestScratchSessionMutations:
    async def test_can_rename_scratch_session(self, user_client, db_session, test_channel):
        current = await user_client.get(
            "/api/v1/sessions/scratch/current",
            params={"parent_channel_id": str(test_channel.id), "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        scratch_id = current.json()["session_id"]

        resp = await user_client.patch(
            f"/api/v1/sessions/{scratch_id}",
            json={"title": "Planning pad"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["title"] == "Planning pad"

        row = await db_session.get(SessionRow, uuid.UUID(scratch_id))
        assert row is not None
        assert row.title == "Planning pad"

    async def test_promote_scratch_to_primary_swaps_sessions(self, user_client, db_session, test_channel):
        primary = SessionRow(
            id=uuid.uuid4(),
            client_id=f"primary-{uuid.uuid4().hex[:6]}",
            bot_id="test-bot",
            channel_id=test_channel.id,
            title="Primary",
        )
        db_session.add(primary)
        await db_session.flush()
        test_channel.active_session_id = primary.id
        await db_session.commit()

        current = await user_client.get(
            "/api/v1/sessions/scratch/current",
            params={"parent_channel_id": str(test_channel.id), "bot_id": "test-bot"},
            headers=AUTH_HEADERS,
        )
        scratch_id = uuid.UUID(current.json()["session_id"])

        resp = await user_client.post(
            f"/api/v1/sessions/{scratch_id}/promote-to-primary",
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["primary_session_id"] == str(scratch_id)
        assert body["demoted_session_id"] == str(primary.id)

        await db_session.refresh(test_channel)
        promoted = await db_session.get(SessionRow, scratch_id)
        demoted = await db_session.get(SessionRow, primary.id)
        assert test_channel.active_session_id == scratch_id
        assert promoted is not None
        assert promoted.session_type == "channel"
        assert promoted.channel_id == test_channel.id
        assert promoted.parent_channel_id is None
        assert demoted is not None
        assert demoted.session_type == "ephemeral"
        assert demoted.parent_channel_id == test_channel.id
        assert demoted.channel_id is None
        assert demoted.is_current is True
