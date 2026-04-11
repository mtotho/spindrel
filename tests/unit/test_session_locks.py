"""Tests for app.services.session_locks — per-session active-request lock.

Lock semantics: acquire/release pair, idempotent release, cancel-flag
isolation, and a janitor sweep for entries leaked by background tasks
cancelled before their try-block runs.
"""
from __future__ import annotations

import time
import uuid

import pytest

from app.services import session_locks


@pytest.fixture(autouse=True)
def _reset_locks():
    """Each test starts with a clean lock table — these are global module
    state and tests in the same process would otherwise leak."""
    session_locks._active.clear()
    session_locks._cancel_requested.clear()
    yield
    session_locks._active.clear()
    session_locks._cancel_requested.clear()


class TestAcquireRelease:
    def test_acquire_first_time_returns_true(self):
        sid = uuid.uuid4()
        assert session_locks.acquire(sid) is True
        assert session_locks.is_active(sid) is True

    def test_acquire_already_held_returns_false(self):
        sid = uuid.uuid4()
        assert session_locks.acquire(sid) is True
        assert session_locks.acquire(sid) is False

    def test_release_drops_lock(self):
        sid = uuid.uuid4()
        session_locks.acquire(sid)
        session_locks.release(sid)
        assert session_locks.is_active(sid) is False
        # Re-acquirable.
        assert session_locks.acquire(sid) is True

    def test_release_idempotent(self):
        sid = uuid.uuid4()
        # No-op release on a never-acquired lock should not raise.
        session_locks.release(sid)
        assert session_locks.is_active(sid) is False


class TestCancelFlags:
    def test_cancel_request_only_when_active(self):
        sid = uuid.uuid4()
        assert session_locks.request_cancel(sid) is False
        session_locks.acquire(sid)
        assert session_locks.request_cancel(sid) is True
        assert session_locks.is_cancel_requested(sid) is True

    def test_release_clears_cancel_flag(self):
        sid = uuid.uuid4()
        session_locks.acquire(sid)
        session_locks.request_cancel(sid)
        session_locks.release(sid)
        assert session_locks.is_cancel_requested(sid) is False

    def test_acquire_clears_stale_cancel_from_previous_run(self):
        """If a STOP arrived after the previous loop finished but before
        the next acquire, the cancel flag would otherwise immediately
        kill the new run. ``acquire`` clears the stale flag."""
        sid = uuid.uuid4()
        session_locks._cancel_requested.add(str(sid))  # simulate stale
        assert session_locks.acquire(sid) is True
        assert session_locks.is_cancel_requested(sid) is False


class TestSweepStale:
    def test_sweep_drops_old_locks(self, monkeypatch):
        """A lock acquired more than TTL seconds ago is swept; younger
        locks survive."""
        sid_old = uuid.uuid4()
        sid_young = uuid.uuid4()

        now = time.monotonic()
        # Drop both into the table directly so we control timestamps.
        session_locks._active[str(sid_old)] = now - 10000  # ~2.7 hours old
        session_locks._active[str(sid_young)] = now - 60  # 1 minute old

        removed = session_locks.sweep_stale(ttl_seconds=7200)
        assert removed == 1
        assert str(sid_old) not in session_locks._active
        assert str(sid_young) in session_locks._active

    def test_sweep_clears_cancel_flag_for_swept_locks(self):
        """A leaked lock with a leaked cancel flag would otherwise cause
        the next acquire of the same id to immediately see
        is_cancel_requested as True."""
        sid = uuid.uuid4()
        now = time.monotonic()
        session_locks._active[str(sid)] = now - 10000
        session_locks._cancel_requested.add(str(sid))

        session_locks.sweep_stale(ttl_seconds=7200)

        assert str(sid) not in session_locks._active
        assert str(sid) not in session_locks._cancel_requested

    def test_sweep_no_locks_returns_zero(self):
        assert session_locks.sweep_stale() == 0

    def test_sweep_all_within_ttl_returns_zero(self):
        sid = uuid.uuid4()
        session_locks.acquire(sid)
        assert session_locks.sweep_stale() == 0
        assert session_locks.is_active(sid) is True
