from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.routers import api_v1_sessions


class _FakeDb:
    def __init__(self, session: Any) -> None:
        self.session = session
        self.committed = False
        self.refreshed: list[Any] = []

    async def get(self, model, item_id):
        return self.session

    async def commit(self):
        self.committed = True

    async def refresh(self, item):
        self.refreshed.append(item)


def _machine_payload(session_id: uuid.UUID) -> dict[str, Any]:
    return {
        "session_id": str(session_id),
        "lease": {
            "lease_id": "lease-1",
            "provider_id": "local_companion",
            "target_id": "target-1",
            "user_id": "user-1",
            "granted_at": "2026-04-26T12:00:00+00:00",
            "expires_at": "2026-04-26T13:00:00+00:00",
            "capabilities": ["shell"],
            "handle_id": "conn-1",
            "connection_id": "conn-1",
            "ready": True,
            "status": "connected",
            "status_label": "Connected",
            "reason": None,
            "checked_at": "2026-04-26T12:00:01+00:00",
            "connected": True,
            "provider_label": "Local Companion",
            "target_label": "Desk",
        },
        "targets": [],
        "ready_target_count": 1,
        "connected_target_count": 1,
    }


def test_api_v1_session_machine_target_lease_route_is_registered():
    assert any(
        route.path == "/sessions/{session_id}/machine-target/lease"
        and "POST" in route.methods
        for route in api_v1_sessions.router.routes
    )


@pytest.mark.asyncio
async def test_api_v1_session_machine_target_lease_forwards(monkeypatch):
    session_id = uuid.uuid4()
    session = SimpleNamespace(id=session_id)
    user = SimpleNamespace(id=uuid.uuid4(), is_admin=True)
    db = _FakeDb(session)
    calls: list[dict[str, Any]] = []

    async def _grant(db, *, session, user, provider_id, target_id, ttl_seconds):
        calls.append(
            {
                "session": session,
                "user": user,
                "provider_id": provider_id,
                "target_id": target_id,
                "ttl_seconds": ttl_seconds,
            }
        )

    async def _payload(db, *, session):
        return _machine_payload(session.id)

    marked_active: list[uuid.UUID] = []
    monkeypatch.setattr(api_v1_sessions, "grant_session_lease", _grant)
    monkeypatch.setattr(api_v1_sessions, "build_session_machine_target_payload", _payload)
    monkeypatch.setattr(api_v1_sessions.presence, "mark_active", lambda user_id: marked_active.append(user_id))

    response = await api_v1_sessions.grant_session_machine_target_lease(
        session_id,
        api_v1_sessions.SessionMachineTargetLeaseRequest(
            provider_id="local_companion",
            target_id="target-1",
            ttl_seconds=300,
        ),
        db,
        user,
    )

    assert response.lease is not None
    assert response.lease.target_id == "target-1"
    assert calls == [
        {
            "session": session,
            "user": user,
            "provider_id": "local_companion",
            "target_id": "target-1",
            "ttl_seconds": 300,
        }
    ]
    assert marked_active == [user.id]
