"""Widget JWT revocation list — `(api_key_id, jti)` keyed.

Verifier-side checks live in `app/dependencies.py::verify_auth_or_user`;
admin endpoint in `app/routers/api_v1_admin/widget_tokens.py`. The hot
path is :func:`is_revoked`, which keeps a small in-process cache so
chatty widget endpoints don't hammer the DB.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services import widget_token_revocations as wtr


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test starts with a clean in-process cache so cross-test cross-talk
    can't mask a regression."""
    wtr._cache_clear()
    yield
    wtr._cache_clear()


class _StubResult:
    def __init__(self, value=None):
        self._value = value

    def first(self):
        if self._value is None:
            return None
        return type("Row", (), {"expires_at": self._value})()

    def scalar(self):
        return self._value

    @property
    def rowcount(self):
        return 1 if self._value else 0


class _StubSession:
    """Just enough surface to test the service without spinning up SQLAlchemy."""

    def __init__(self):
        self._rows: dict[tuple[uuid.UUID, str], datetime] = {}
        self.executes = 0
        self.committed = False

    async def execute(self, stmt, params=None):
        self.executes += 1
        text = str(stmt).lower()
        if "delete from widget_token_revocations" in text:
            # Emulate deletion of expired rows.
            stale = [
                k for k, v in self._rows.items()
                if v < datetime.now(timezone.utc)
            ]
            for k in stale:
                self._rows.pop(k, None)
            return _StubResult(len(stale))
        # Default: SELECT one row by (api_key_id, jti) — encoded in the
        # stmt's where clause via SQLAlchemy. We approximate by stashing
        # the last lookup args on the session via _last_lookup.
        return _StubResult(self._last_lookup)

    async def get(self, model, key):
        return None  # no existing row

    def add(self, obj):
        self._rows[(obj.api_key_id, obj.jti)] = obj.expires_at

    async def flush(self):
        pass

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_is_revoked_returns_false_when_no_row(monkeypatch):
    db = _StubSession()
    db._last_lookup = None  # type: ignore[attr-defined]
    api_key_id = uuid.uuid4()
    assert (
        await wtr.is_revoked(db, api_key_id=api_key_id, jti="abc-123") is False
    )


@pytest.mark.asyncio
async def test_revoke_then_is_revoked_returns_true():
    db = _StubSession()
    db._last_lookup = None  # type: ignore[attr-defined]
    api_key_id = uuid.uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    await wtr.revoke(db, api_key_id=api_key_id, jti="abc-123", expires_at=expires_at)
    # revoke primes the positive cache, so verify hits cache (not DB)
    db.executes = 0
    assert (
        await wtr.is_revoked(db, api_key_id=api_key_id, jti="abc-123") is True
    )
    assert db.executes == 0, "cache should serve the immediate post-revoke check"


@pytest.mark.asyncio
async def test_cache_serves_repeat_negative_lookups():
    db = _StubSession()
    db._last_lookup = None  # type: ignore[attr-defined]
    api_key_id = uuid.uuid4()
    await wtr.is_revoked(db, api_key_id=api_key_id, jti="abc")
    db.executes = 0
    await wtr.is_revoked(db, api_key_id=api_key_id, jti="abc")
    assert db.executes == 0, "second lookup must come from cache"


@pytest.mark.asyncio
async def test_cache_serves_repeat_positive_lookups():
    db = _StubSession()
    api_key_id = uuid.uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    db._last_lookup = expires_at  # type: ignore[attr-defined]
    assert await wtr.is_revoked(db, api_key_id=api_key_id, jti="x") is True
    db.executes = 0
    db._last_lookup = None  # type: ignore[attr-defined]
    # Cached True must be returned even though DB would now miss.
    assert await wtr.is_revoked(db, api_key_id=api_key_id, jti="x") is True
    assert db.executes == 0


@pytest.mark.asyncio
async def test_expired_revocation_is_treated_as_inactive():
    db = _StubSession()
    api_key_id = uuid.uuid4()
    # Past-dated revocation — verifier should NOT honor it (the JWT itself
    # is already expired and the row will be purged opportunistically).
    db._last_lookup = datetime.now(timezone.utc) - timedelta(seconds=10)  # type: ignore[attr-defined]
    assert await wtr.is_revoked(db, api_key_id=api_key_id, jti="old") is False


@pytest.mark.asyncio
async def test_purge_drops_only_expired_rows():
    db = _StubSession()
    api_key_id = uuid.uuid4()
    fresh = datetime.now(timezone.utc) + timedelta(minutes=5)
    stale = datetime.now(timezone.utc) - timedelta(minutes=5)
    db._rows[(api_key_id, "fresh")] = fresh
    db._rows[(api_key_id, "stale")] = stale
    deleted = await wtr.purge_expired(db)
    assert deleted == 1
    assert (api_key_id, "fresh") in db._rows
    assert (api_key_id, "stale") not in db._rows


@pytest.mark.asyncio
async def test_revoke_is_idempotent():
    db = _StubSession()
    api_key_id = uuid.uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    await wtr.revoke(db, api_key_id=api_key_id, jti="dup", expires_at=expires_at)
    await wtr.revoke(db, api_key_id=api_key_id, jti="dup", expires_at=expires_at)
    # Cache stays True; calling twice doesn't raise.
    db._last_lookup = expires_at  # type: ignore[attr-defined]
    assert await wtr.is_revoked(db, api_key_id=api_key_id, jti="dup") is True
