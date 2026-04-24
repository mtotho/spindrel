"""Phase O — machine_control drift seams.

Companion to ``test_machine_target_sessions.py``, which covers the happy-path
grant + conflict rejection shape with a fake DB. This file drift-pins the
seams the Phase D happy-path sweep skipped:

  1. ``validate_current_execution_policy`` autonomous-origin bypass —
     ``heartbeat``/``task``/``subagent``/``hygiene`` runs ALWAYS deny
     machine control, even with a valid lease. Silent-skip contract.
  2. ``validate_current_execution_policy`` admin-only gate — non-admin
     active user is denied.
  3. ``validate_current_execution_policy`` user-mismatch — lease belongs
     to user A but request rides on user B's ContextVar → denied.
  4. ``validate_current_execution_policy`` expired lease → denied
     (silent time-UPDATE seam).
  5. ``validate_current_execution_policy`` leased-target-not-ready →
     denied (orphan pointer).
  6. ``get_session_lease`` shape-coercion — metadata with missing required
     fields returns None (silent-skip on malformed JSONB).
  7. ``build_session_machine_target_payload`` auto-clears expired lease —
     fire-and-forget cleanup via the same response path.
  8. ``_find_conflicting_lease`` respects expiration — an expired lease
     on target T does NOT block a new grant on T.
  9. ``_find_conflicting_lease`` respects ``exclude_session_id`` — a
     session's own lease doesn't conflict with itself on renewal.
  10. ``delete_machine_target`` clears leases across ALL sessions pointing
     at the removed (provider, target) — multi-row sync contract.
  11. ``_PROVIDER_CACHE`` reuse — a second lookup returns the same
     instance without re-importing.

Seams deliberately NOT covered: enrollment end-to-end (requires provider
module I/O), `build_providers_status` + `build_targets_status` happy path
(already covered by the companion file), FastAPI request wiring (out of
unit-test scope).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy.orm.attributes import flag_modified

from app.agent.context import (
    current_run_origin,
    current_session_id,
    current_user_id,
)
from app.db.models import Session as SessionRow, User
from app.services import machine_control, presence


# ---------------------------------------------------------------------------
# Fakes — reuse the shape from test_machine_target_sessions.py so the two
# files stay readable side-by-side.
# ---------------------------------------------------------------------------


class _FakeProvider:
    provider_id = "local_companion"
    label = "Local Companion"
    driver = "companion"
    supports_enroll = True
    supports_remove_target = True

    def __init__(self, *, connected: bool = True):
        self._connected = connected
        self.removed_targets: list[str] = []
        self.target = {
            "target_id": "target-1",
            "driver": "companion",
            "label": "Desk",
            "hostname": "workstation",
            "platform": "linux",
            "capabilities": ["shell"],
            "enrolled_at": "2026-04-23T12:00:00+00:00",
            "last_seen_at": "2026-04-23T12:05:00+00:00",
        }

    def list_targets(self) -> list[dict[str, Any]]:
        return [dict(self.target)]

    def get_target(self, target_id: str) -> dict[str, Any] | None:
        if target_id == self.target["target_id"]:
            return dict(self.target)
        return None

    def get_target_status(self, target_id: str) -> dict[str, Any] | None:
        if target_id != self.target["target_id"]:
            return None
        if self._connected:
            return {
                "ready": True,
                "status": "connected",
                "reason": None,
                "checked_at": "2026-04-23T12:06:00+00:00",
                "handle_id": "conn-1",
            }
        return {
            "ready": False,
            "status": "offline",
            "reason": "The companion is not currently connected.",
            "checked_at": "2026-04-23T12:06:00+00:00",
            "handle_id": None,
        }

    async def probe_target(self, db, *, target_id: str):
        _ = db
        status = self.get_target_status(target_id)
        if status is None:
            raise ValueError("Unknown machine target.")
        return status

    async def enroll(self, db, *, server_base_url, label=None, config=None):
        raise NotImplementedError

    async def remove_target(self, db, target_id: str) -> bool:
        self.removed_targets.append(target_id)
        return True

    async def register_connected_target(self, db, **_kwargs):
        raise NotImplementedError

    async def inspect_command(self, target_id, command):
        raise NotImplementedError

    async def exec_command(self, target_id, command, working_dir=""):
        raise NotImplementedError


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return list(self._rows)


class _FakeDb:
    def __init__(self, sessions: list[SessionRow] | None = None, users: list[User] | None = None):
        self._sessions = {s.id: s for s in (sessions or [])}
        self._users = {u.id: u for u in (users or [])}
        self.commit_count = 0

    async def execute(self, _q):
        return _FakeScalarResult(list(self._sessions.values()))

    async def get(self, model, pk):
        if model is SessionRow:
            return self._sessions.get(pk)
        if model is User:
            return self._users.get(pk)
        return None

    async def commit(self):
        self.commit_count += 1

    async def refresh(self, _obj):
        pass


def _make_user(*, is_admin: bool = True, is_active: bool = True) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"user-{uuid.uuid4().hex[:8]}@test.com",
        display_name="Machine User",
        auth_method="local",
        password_hash="fakehash",
        is_admin=is_admin,
        is_active=is_active,
        integration_config={},
    )


def _make_session(*, lease: dict[str, Any] | None = None) -> SessionRow:
    meta = {}
    if lease is not None:
        meta[machine_control.LEASE_METADATA_KEY] = lease
    return SessionRow(
        id=uuid.uuid4(),
        client_id=f"session-{uuid.uuid4().hex[:8]}",
        bot_id="test-bot",
        metadata_=meta,
    )


def _valid_lease(user_id: uuid.UUID, *, expires_delta: timedelta = timedelta(minutes=10)) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "lease_id": str(uuid.uuid4()),
        "provider_id": "local_companion",
        "target_id": "target-1",
        "user_id": str(user_id),
        "granted_at": now.isoformat(),
        "expires_at": (now + expires_delta).isoformat(),
        "capabilities": ["shell"],
        "handle_id": "conn-1",
        "connection_id": "conn-1",
    }


@pytest.fixture
def fake_provider(monkeypatch):
    provider = _FakeProvider()
    monkeypatch.setattr(machine_control, "get_provider", lambda _pid: provider)
    monkeypatch.setattr(machine_control, "list_provider_ids", lambda: ["local_companion"])
    return provider


@pytest.fixture
def _presence_always_active(monkeypatch):
    monkeypatch.setattr(presence, "is_active", lambda _uid: True)


@pytest.fixture(autouse=True)
def _reset_contextvars():
    tokens = []
    yield tokens
    for var, token in reversed(tokens):
        var.reset(token)


def _set_ctx(*, user_id=None, session_id=None, origin=None):
    """Set the three ContextVars the policy reads. Reset via fixture."""
    if user_id is not None:
        current_user_id.set(user_id)
    if session_id is not None:
        current_session_id.set(session_id)
    if origin is not None:
        current_run_origin.set(origin)


# ---------------------------------------------------------------------------
# O.1 — Autonomous-origin bypass (silent-skip contract)
# ---------------------------------------------------------------------------


class TestAutonomousOriginBypass:
    @pytest.mark.parametrize(
        "origin", ["heartbeat", "task", "subagent", "hygiene"]
    )
    @pytest.mark.asyncio
    async def test_autonomous_origin_denies_even_with_valid_lease(
        self, origin, fake_provider, _presence_always_active, monkeypatch
    ):
        """Autonomous runs (heartbeat/task/subagent/hygiene) NEVER get
        machine control, even with a valid admin user + active presence +
        current lease. The policy denies at the origin check before user
        or lease resolution.
        """
        user = _make_user(is_admin=True)
        lease = _valid_lease(user.id)
        session = _make_session(lease=lease)
        db = _FakeDb(sessions=[session], users=[user])

        monkeypatch.setattr(
            "app.db.engine.async_session",
            lambda: _FakeAsyncSessionCtx(db),
        )

        _set_ctx(user_id=user.id, session_id=session.id, origin=origin)

        result = await machine_control.validate_current_execution_policy(
            "interactive_session"
        )

        assert result.allowed is False
        assert origin in (result.reason or "")


# Small context-manager shim so validate_current_execution_policy can
# ``async with async_session() as db`` against our _FakeDb.
class _FakeAsyncSessionCtx:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *_):
        return False


# ---------------------------------------------------------------------------
# O.2 — Admin-only gate
# ---------------------------------------------------------------------------


class TestAdminGate:
    @pytest.mark.asyncio
    async def test_non_admin_user_is_denied(
        self, fake_provider, _presence_always_active, monkeypatch
    ):
        """Even an active signed-in user without ``is_admin`` is denied —
        machine-control tools are admin-only in this build."""
        user = _make_user(is_admin=False, is_active=True)
        session = _make_session()
        db = _FakeDb(sessions=[session], users=[user])

        monkeypatch.setattr(
            "app.db.engine.async_session",
            lambda: _FakeAsyncSessionCtx(db),
        )

        _set_ctx(user_id=user.id, session_id=session.id)

        result = await machine_control.validate_current_execution_policy(
            "interactive_user"
        )

        assert result.allowed is False
        assert "admin" in (result.reason or "").lower()

    @pytest.mark.asyncio
    async def test_no_user_id_contextvar_is_denied(self, fake_provider):
        """Policies stricter than ``normal`` require a signed-in user.
        ``current_user_id`` unset → denied without touching the DB.
        """
        # Don't set user_id.
        result = await machine_control.validate_current_execution_policy(
            "interactive_user"
        )
        assert result.allowed is False
        assert "signed-in user" in (result.reason or "")


# ---------------------------------------------------------------------------
# O.3 — Lease user-mismatch (multi-actor seam)
# ---------------------------------------------------------------------------


class TestLeaseUserMismatch:
    @pytest.mark.asyncio
    async def test_lease_owned_by_different_user_is_denied(
        self, fake_provider, _presence_always_active, monkeypatch
    ):
        """Session has a valid lease, but the lease's ``user_id`` is
        different from the current ``current_user_id``. Denied —
        machine-control leases are not transferable across users within
        a single session.
        """
        owner = _make_user(is_admin=True)
        intruder = _make_user(is_admin=True)
        lease = _valid_lease(owner.id)
        session = _make_session(lease=lease)
        db = _FakeDb(sessions=[session], users=[owner, intruder])

        monkeypatch.setattr(
            "app.db.engine.async_session",
            lambda: _FakeAsyncSessionCtx(db),
        )

        _set_ctx(user_id=intruder.id, session_id=session.id)

        result = await machine_control.validate_current_execution_policy(
            "interactive_session"
        )

        assert result.allowed is False
        assert "different user" in (result.reason or "")


# ---------------------------------------------------------------------------
# O.4 — Expired lease (silent time-UPDATE seam)
# ---------------------------------------------------------------------------


class TestLeaseExpiry:
    @pytest.mark.asyncio
    async def test_expired_lease_is_denied(
        self, fake_provider, _presence_always_active, monkeypatch
    ):
        user = _make_user(is_admin=True)
        lease = _valid_lease(user.id, expires_delta=timedelta(minutes=-1))
        session = _make_session(lease=lease)
        db = _FakeDb(sessions=[session], users=[user])

        monkeypatch.setattr(
            "app.db.engine.async_session",
            lambda: _FakeAsyncSessionCtx(db),
        )

        _set_ctx(user_id=user.id, session_id=session.id)

        result = await machine_control.validate_current_execution_policy(
            "interactive_session"
        )

        assert result.allowed is False
        assert "expired" in (result.reason or "").lower()


# ---------------------------------------------------------------------------
# O.5 — Leased target not connected (orphan pointer)
# ---------------------------------------------------------------------------


class TestLeasedTargetNotConnected:
    @pytest.mark.asyncio
    async def test_disconnected_target_denies_policy(
        self, _presence_always_active, monkeypatch
    ):
        """Lease is valid, user matches, but cached/probed status reports the
        returns None (target offline / crashed). Denied."""
        provider = _FakeProvider(connected=False)
        monkeypatch.setattr(
            machine_control, "get_provider", lambda _pid: provider
        )
        monkeypatch.setattr(
            machine_control, "list_provider_ids", lambda: ["local_companion"]
        )

        user = _make_user(is_admin=True)
        lease = _valid_lease(user.id)
        session = _make_session(lease=lease)
        db = _FakeDb(sessions=[session], users=[user])

        monkeypatch.setattr(
            "app.db.engine.async_session",
            lambda: _FakeAsyncSessionCtx(db),
        )

        _set_ctx(user_id=user.id, session_id=session.id)

        result = await machine_control.validate_current_execution_policy(
            "interactive_session"
        )

        assert result.allowed is False
        assert "not currently connected" in (result.reason or "").lower()


# ---------------------------------------------------------------------------
# O.6 — get_session_lease shape-coercion (malformed metadata)
# ---------------------------------------------------------------------------


class TestGetSessionLeaseShapeCoercion:
    def test_none_session_returns_none(self):
        assert machine_control.get_session_lease(None) is None

    def test_no_metadata_key_returns_none(self):
        session = _make_session()
        assert machine_control.get_session_lease(session) is None

    def test_non_dict_lease_value_returns_none(self):
        session = _make_session()
        session.metadata_ = {machine_control.LEASE_METADATA_KEY: "not-a-dict"}
        assert machine_control.get_session_lease(session) is None

    def test_missing_required_field_returns_none(self):
        """Each required field (provider_id, target_id, lease_id, user_id,
        expires_at, granted_at) must be present AND non-empty. Any missing
        → silent None.
        """
        user_id = uuid.uuid4()
        base = _valid_lease(user_id)
        # Drop each required field in turn and assert None.
        for missing in ["target_id", "lease_id", "user_id", "expires_at", "granted_at"]:
            corrupted = dict(base)
            corrupted[missing] = ""
            session = _make_session(lease=corrupted)
            assert (
                machine_control.get_session_lease(session) is None
            ), f"Missing {missing} must yield None"

    def test_missing_provider_id_defaults_to_legacy(self):
        """Absent ``provider_id`` falls back to the ``LEGACY_PROVIDER_ID``
        constant — pre-multi-provider sessions stay readable."""
        user_id = uuid.uuid4()
        lease = _valid_lease(user_id)
        lease["provider_id"] = ""
        session = _make_session(lease=lease)

        resolved = machine_control.get_session_lease(session)
        assert resolved is not None
        assert resolved["provider_id"] == machine_control.LEGACY_PROVIDER_ID


# ---------------------------------------------------------------------------
# O.7 — build_session_machine_target_payload auto-clear (fire-and-forget)
# ---------------------------------------------------------------------------


class TestBuildPayloadAutoClear:
    @pytest.mark.asyncio
    async def test_expired_lease_is_auto_cleared_on_build(self, fake_provider):
        """When the response-building helper is called with an expired
        lease, it clears the lease from the session metadata and commits —
        the next read sees no stale lease. Fire-and-forget cleanup path.
        """
        user = _make_user(is_admin=True)
        stale = _valid_lease(user.id, expires_delta=timedelta(minutes=-5))
        session = _make_session(lease=stale)
        db = _FakeDb(sessions=[session], users=[user])

        payload = await machine_control.build_session_machine_target_payload(
            db, session=session
        )

        assert payload["lease"] is None
        assert (
            machine_control.LEASE_METADATA_KEY
            not in (session.metadata_ or {})
        )
        assert db.commit_count == 1


# ---------------------------------------------------------------------------
# O.8 — _find_conflicting_lease respects expiration
# ---------------------------------------------------------------------------


class TestConflictDetection:
    @pytest.mark.asyncio
    async def test_expired_lease_on_target_does_not_block_new_grant(
        self, fake_provider
    ):
        """A previous session's EXPIRED lease on target T does not
        register as a conflict — the new grant succeeds.
        """
        owner_a = _make_user()
        owner_b = _make_user()
        stale_session = _make_session(
            lease=_valid_lease(owner_a.id, expires_delta=timedelta(minutes=-5))
        )
        fresh_session = _make_session()
        db = _FakeDb(sessions=[stale_session, fresh_session])

        lease = await machine_control.grant_session_lease(
            db,
            session=fresh_session,
            user=owner_b,
            provider_id="local_companion",
            target_id="target-1",
            ttl_seconds=300,
        )

        assert lease["user_id"] == str(owner_b.id)
        assert lease["target_id"] == "target-1"

    @pytest.mark.asyncio
    async def test_renewing_own_lease_does_not_conflict_with_self(
        self, fake_provider
    ):
        """Re-granting a lease on the same session is allowed —
        ``exclude_session_id`` in ``_find_conflicting_lease`` filters out
        the caller's own row so a session can renew its own lease.
        """
        user = _make_user()
        existing = _valid_lease(user.id)
        session = _make_session(lease=existing)
        db = _FakeDb(sessions=[session])

        new_lease = await machine_control.grant_session_lease(
            db,
            session=session,
            user=user,
            provider_id="local_companion",
            target_id="target-1",
            ttl_seconds=600,
        )

        assert new_lease["lease_id"] != existing["lease_id"]
        assert new_lease["target_id"] == "target-1"


# ---------------------------------------------------------------------------
# O.9 — delete_machine_target clears every session's matching lease
# ---------------------------------------------------------------------------


class TestDeleteTargetMultiSessionClear:
    @pytest.mark.asyncio
    async def test_delete_target_clears_matching_leases_across_sessions(
        self, fake_provider
    ):
        """Removing a target sweeps every session whose lease pointed at
        ``(provider_id, target_id)``. Non-matching leases are untouched.
        """
        user = _make_user()
        # Three sessions: two lease the target being removed, one leases
        # a different target_id.
        s_a = _make_session(lease=_valid_lease(user.id))
        s_b = _make_session(lease=_valid_lease(user.id))
        other = _valid_lease(user.id)
        other["target_id"] = "target-other"
        s_c = _make_session(lease=other)
        db = _FakeDb(sessions=[s_a, s_b, s_c])

        removed = await machine_control.delete_machine_target(
            db,
            provider_id="local_companion",
            target_id="target-1",
        )
        assert removed is True
        # Two leases cleared, one preserved.
        assert (
            machine_control.LEASE_METADATA_KEY not in (s_a.metadata_ or {})
        )
        assert (
            machine_control.LEASE_METADATA_KEY not in (s_b.metadata_ or {})
        )
        assert (
            machine_control.LEASE_METADATA_KEY in (s_c.metadata_ or {})
        )


# ---------------------------------------------------------------------------
# O.10 — _PROVIDER_CACHE reuse across calls
# ---------------------------------------------------------------------------


class TestProviderCacheReuse:
    def test_same_provider_id_returns_cached_instance(self, monkeypatch):
        """Two ``get_provider`` calls for the same provider_id must
        return the exact same instance — the cache dict is keyed on
        provider_id. A regression that skips the cache would re-run
        the dynamic-import path on every tool dispatch.
        """
        # Seed the cache directly to avoid the real filesystem import path.
        sentinel = _FakeProvider()
        machine_control._PROVIDER_CACHE["local_companion"] = sentinel
        try:
            assert machine_control.get_provider("local_companion") is sentinel
            assert machine_control.get_provider("local_companion") is sentinel
        finally:
            machine_control._PROVIDER_CACHE.pop("local_companion", None)
