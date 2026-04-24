import uuid

import pytest

from app.db.models import Session, User
from app.services import machine_control


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return list(self._rows)


class _FakeDbSession:
    def __init__(self, sessions):
        self._sessions = {session.id: session for session in sessions}
        self.commit_count = 0
        self.refresh_count = 0

    async def execute(self, _query):
        return _FakeScalarResult(self._sessions.values())

    async def get(self, _model, session_id):
        return self._sessions.get(session_id)

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, _obj):
        self.refresh_count += 1


class _FakeProvider:
    provider_id = "local_companion"
    label = "Local Companion"
    driver = "companion"
    supports_enroll = True
    supports_remove_target = True
    supports_profiles = False

    def __init__(self):
        self.target = {
            "target_id": "target-1",
            "driver": "companion",
            "label": "Desk",
            "hostname": "workstation",
            "platform": "linux",
            "capabilities": ["shell"],
            "enrolled_at": "2026-04-23T12:00:00+00:00",
            "last_seen_at": "2026-04-23T12:05:00+00:00",
            "metadata": {"room": "office"},
        }
        self.connection = {
            "target_id": "target-1",
            "handle_id": "conn-1",
            "label": "Desk",
            "hostname": "workstation",
            "platform": "linux",
            "capabilities": ["shell"],
        }

    def list_targets(self):
        return [self.target]

    def get_target(self, target_id: str):
        if target_id == self.target["target_id"]:
            return dict(self.target)
        return None

    def get_target_status(self, target_id: str):
        if target_id == self.target["target_id"]:
            return {
                "ready": True,
                "status": "connected",
                "reason": None,
                "checked_at": "2026-04-23T12:06:00+00:00",
                "handle_id": self.connection["handle_id"],
            }
        return None

    def list_profiles(self):
        return []

    def get_profile(self, profile_id: str):
        _ = profile_id
        return None

    async def probe_target(self, db, *, target_id: str):
        _ = db
        status = self.get_target_status(target_id)
        if status is None:
            raise ValueError("Unknown machine target.")
        return status

    async def enroll(self, db, *, server_base_url, label=None, config=None):
        raise NotImplementedError

    async def remove_target(self, db, target_id: str):
        raise NotImplementedError

    async def create_profile(self, db, *, label=None, config=None):
        raise NotImplementedError

    async def update_profile(self, db, *, profile_id: str, label=None, config=None):
        raise NotImplementedError

    async def delete_profile(self, db, profile_id: str):
        raise NotImplementedError

    async def register_connected_target(self, db, *, target_id: str, label=None, hostname=None, platform=None, capabilities=None):
        raise NotImplementedError

    async def inspect_command(self, target_id: str, command: str):
        raise NotImplementedError

    async def exec_command(self, target_id: str, command: str, working_dir: str = ""):
        raise NotImplementedError


def _make_user() -> User:
    return User(
        id=uuid.uuid4(),
        email=f"user-{uuid.uuid4().hex[:8]}@test.com",
        display_name="Machine Control User",
        auth_method="local",
        password_hash="fakehash",
        is_admin=True,
        is_active=True,
        integration_config={},
    )


def _make_session() -> Session:
    return Session(
        id=uuid.uuid4(),
        client_id=f"session-{uuid.uuid4().hex[:8]}",
        bot_id="test-bot",
        metadata_={},
    )


@pytest.fixture
def fake_provider(monkeypatch):
    provider = _FakeProvider()
    monkeypatch.setattr(machine_control, "get_provider", lambda provider_id: provider)
    monkeypatch.setattr(machine_control, "list_provider_ids", lambda: ["local_companion"])
    return provider


@pytest.mark.asyncio
async def test_grant_session_lease_and_build_payload(fake_provider):
    user = _make_user()
    session = _make_session()
    db = _FakeDbSession([session])

    lease = await machine_control.grant_session_lease(
        db,
        session=session,
        user=user,
        provider_id="local_companion",
        target_id="target-1",
        ttl_seconds=300,
    )
    payload = await machine_control.build_session_machine_target_payload(db, session=session)

    assert lease["provider_id"] == "local_companion"
    assert lease["target_id"] == "target-1"
    assert lease["user_id"] == str(user.id)
    assert lease["handle_id"] == "conn-1"
    assert lease["connection_id"] == "conn-1"
    assert payload["lease"]["provider_id"] == "local_companion"
    assert payload["lease"]["target_label"] == "Desk"
    assert payload["lease"]["ready"] is True
    assert payload["targets"] == [{
        "provider_id": "local_companion",
        "provider_label": "Local Companion",
        "target_id": "target-1",
        "driver": "companion",
        "label": "Desk",
        "hostname": "workstation",
        "platform": "linux",
        "capabilities": ["shell"],
        "enrolled_at": "2026-04-23T12:00:00+00:00",
        "last_seen_at": "2026-04-23T12:05:00+00:00",
        "ready": True,
        "status": "connected",
        "status_label": "Connected",
        "reason": None,
        "checked_at": "2026-04-23T12:06:00+00:00",
        "handle_id": "conn-1",
        "connected": True,
        "connection_id": "conn-1",
        "profile_id": None,
        "profile_label": None,
        "metadata": {"room": "office"},
    }]
    assert db.commit_count == 1
    assert db.refresh_count == 1


@pytest.mark.asyncio
async def test_grant_session_lease_rejects_conflicting_target(fake_provider):
    user = _make_user()
    session_one = _make_session()
    session_two = _make_session()
    db = _FakeDbSession([session_one, session_two])

    await machine_control.grant_session_lease(
        db,
        session=session_one,
        user=user,
        provider_id="local_companion",
        target_id="target-1",
        ttl_seconds=300,
    )

    with pytest.raises(RuntimeError) as excinfo:
        await machine_control.grant_session_lease(
            db,
            session=session_two,
            user=user,
            provider_id="local_companion",
            target_id="target-1",
            ttl_seconds=300,
        )

    assert "already leased" in str(excinfo.value).lower()
