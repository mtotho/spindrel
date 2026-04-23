import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.models import Session, User
from app.dependencies import get_db, verify_auth_or_user, verify_user
from app.routers.api_v1 import router as api_v1_router
from app.services import integration_settings
from app.services.local_machine_control import create_enrollment, grant_session_lease
from integrations.local_companion.bridge import bridge
from tests.integration.conftest import _TEST_REGISTRY, _get_test_bot

pytestmark = pytest.mark.asyncio


async def _create_user(db_session, *, is_admin: bool) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"user-{uuid.uuid4().hex[:8]}@test.com",
        display_name="Machine Control User",
        auth_method="local",
        password_hash="fakehash",
        is_admin=is_admin,
        integration_config={},
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def admin_user_client(db_session):
    user = await _create_user(db_session, is_admin=True)

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(api_v1_router)

    async def _override_get_db():
        yield db_session

    async def _override_verify_user():
        return user

    async def _override_auth_or_user():
        return user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[verify_user] = _override_verify_user
    app.dependency_overrides[verify_auth_or_user] = _override_auth_or_user

    cache_backup = integration_settings._cache.copy()
    secret_backup = integration_settings._secret_keys.copy()
    integration_settings._cache.clear()
    integration_settings._secret_keys.clear()

    with (
        patch("app.agent.bots._registry", _TEST_REGISTRY),
        patch("app.agent.bots.get_bot", side_effect=_get_test_bot),
        patch("app.agent.persona.get_persona", return_value=None),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, user

    for target in [row["target_id"] for row in bridge.list_targets()]:
        await bridge.unregister_target(target)
    integration_settings._cache.clear()
    integration_settings._cache.update(cache_backup)
    integration_settings._secret_keys.clear()
    integration_settings._secret_keys.update(secret_backup)
    app.dependency_overrides.clear()


async def test_admin_can_view_and_grant_machine_target_lease(admin_user_client, db_session):
    client, user = admin_user_client
    session = Session(
        id=uuid.uuid4(),
        client_id=f"session-{uuid.uuid4().hex[:8]}",
        bot_id="test-bot",
        metadata_={},
    )
    db_session.add(session)
    await db_session.flush()

    enrolled = await create_enrollment(db_session, label="Desk")

    async def _send(_payload):
        return None

    await bridge.register(
        _send,
        target_id=enrolled["target_id"],
        label="Desk",
        hostname="workstation",
        platform="linux",
        capabilities=["shell"],
    )

    initial = await client.get(
        f"/api/v1/sessions/{session.id}/machine-target",
        headers={"Authorization": "Bearer fake-jwt"},
    )
    assert initial.status_code == 200, initial.text
    initial_body = initial.json()
    assert initial_body["lease"] is None
    assert initial_body["targets"][0]["target_id"] == enrolled["target_id"]
    assert initial_body["targets"][0]["connected"] is True

    granted = await client.post(
        f"/api/v1/sessions/{session.id}/machine-target/lease",
        headers={"Authorization": "Bearer fake-jwt"},
        json={"target_id": enrolled["target_id"], "ttl_seconds": 300},
    )
    assert granted.status_code == 200, granted.text
    granted_body = granted.json()
    assert granted_body["lease"]["target_id"] == enrolled["target_id"]
    assert granted_body["lease"]["user_id"] == str(user.id)
    assert granted_body["lease"]["connected"] is True
    assert granted_body["lease"]["target_label"] == "Desk"


async def test_machine_target_lease_conflicts_across_sessions(admin_user_client, db_session):
    _client, user = admin_user_client
    session_one = Session(
        id=uuid.uuid4(),
        client_id=f"session-{uuid.uuid4().hex[:8]}",
        bot_id="test-bot",
        metadata_={},
    )
    session_two = Session(
        id=uuid.uuid4(),
        client_id=f"session-{uuid.uuid4().hex[:8]}",
        bot_id="test-bot",
        metadata_={},
    )
    db_session.add_all([session_one, session_two])
    await db_session.flush()

    enrolled = await create_enrollment(db_session, label="Desk")

    async def _send(_payload):
        return None

    await bridge.register(
        _send,
        target_id=enrolled["target_id"],
        label="Desk",
        hostname="workstation",
        platform="linux",
        capabilities=["shell"],
    )

    await grant_session_lease(
        db_session,
        session=session_one,
        user=user,
        target_id=enrolled["target_id"],
        ttl_seconds=300,
    )

    conflict = await _client.post(
        f"/api/v1/sessions/{session_two.id}/machine-target/lease",
        headers={"Authorization": "Bearer fake-jwt"},
        json={"target_id": enrolled["target_id"], "ttl_seconds": 300},
    )
    assert conflict.status_code == 409
    assert "already leased" in conflict.json()["detail"].lower()
