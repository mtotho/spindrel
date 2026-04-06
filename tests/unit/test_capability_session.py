"""Unit tests for the capability session store."""
import time
from unittest.mock import patch

import pytest

from app.agent.capability_session import (
    _approved,
    _sessions,
    activate,
    active_count,
    approve,
    cleanup_stale,
    clear_session,
    get_activated,
    is_activated,
    is_approved,
    total_activations,
)


@pytest.fixture(autouse=True)
def clear_store():
    _sessions.clear()
    _approved.clear()
    yield
    _sessions.clear()
    _approved.clear()


class TestActivateAndQuery:
    def test_activate_single(self):
        activate("sess-1", "code-review")
        assert is_activated("sess-1", "code-review")
        assert not is_activated("sess-1", "qa")

    def test_activate_multiple(self):
        activate("sess-1", "code-review")
        activate("sess-1", "data-analyst")
        assert get_activated("sess-1") == {"code-review", "data-analyst"}

    def test_activate_idempotent(self):
        activate("sess-1", "code-review")
        activate("sess-1", "code-review")
        assert get_activated("sess-1") == {"code-review"}
        assert total_activations() == 1

    def test_get_activated_empty(self):
        assert get_activated("sess-1") == set()

    def test_get_activated_none_session(self):
        assert get_activated(None) == set()

    def test_is_activated_none_session(self):
        assert not is_activated(None, "code-review")


class TestSessionIsolation:
    def test_different_sessions_independent(self):
        activate("sess-1", "code-review")
        activate("sess-2", "qa")
        assert get_activated("sess-1") == {"code-review"}
        assert get_activated("sess-2") == {"qa"}
        assert not is_activated("sess-1", "qa")
        assert not is_activated("sess-2", "code-review")

    def test_active_count(self):
        activate("sess-1", "code-review")
        activate("sess-2", "qa")
        assert active_count() == 2

    def test_total_activations(self):
        activate("sess-1", "code-review")
        activate("sess-1", "qa")
        activate("sess-2", "data-analyst")
        assert total_activations() == 3


class TestClearSession:
    def test_clear_removes_all(self):
        activate("sess-1", "code-review")
        activate("sess-1", "qa")
        count = clear_session("sess-1")
        assert count == 2
        assert get_activated("sess-1") == set()
        assert active_count() == 0

    def test_clear_nonexistent_session(self):
        count = clear_session("nonexistent")
        assert count == 0

    def test_clear_doesnt_affect_others(self):
        activate("sess-1", "code-review")
        activate("sess-2", "qa")
        clear_session("sess-1")
        assert get_activated("sess-2") == {"qa"}


class TestCleanupStale:
    def test_cleanup_removes_old_sessions(self):
        # Manually insert a stale entry
        _sessions["old-sess"] = {"code-review": time.monotonic() - 5 * 3600}
        activate("fresh-sess", "qa")

        removed = cleanup_stale()
        assert removed == 1
        assert "old-sess" not in _sessions
        assert is_activated("fresh-sess", "qa")

    def test_cleanup_keeps_fresh_sessions(self):
        activate("sess-1", "code-review")
        removed = cleanup_stale()
        assert removed == 0
        assert is_activated("sess-1", "code-review")

    def test_cleanup_partial_staleness(self):
        """Session with one fresh and one stale entry stays (any fresh entry keeps the session)."""
        _sessions["mixed-sess"] = {
            "old-cap": time.monotonic() - 5 * 3600,
            "fresh-cap": time.monotonic(),
        }
        removed = cleanup_stale()
        assert removed == 0  # session kept because fresh-cap is recent

    def test_cleanup_stale_clears_old_approvals(self):
        """Stale approval-only entries are cleaned up too."""
        _approved["old-sess"] = {"code-review": time.monotonic() - 5 * 3600}
        removed = cleanup_stale()
        assert removed == 1
        assert "old-sess" not in _approved


class TestApproval:
    def test_approve_and_is_approved(self):
        approve("sess-1", "code-review")
        assert is_approved("sess-1", "code-review")

    def test_approve_different_capabilities(self):
        approve("sess-1", "code-review")
        approve("sess-1", "data-analyst")
        assert is_approved("sess-1", "code-review")
        assert is_approved("sess-1", "data-analyst")
        assert not is_approved("sess-1", "qa")

    def test_is_approved_none_session(self):
        assert not is_approved(None, "code-review")

    def test_is_approved_unknown_session(self):
        assert not is_approved("nonexistent", "code-review")

    def test_clear_session_clears_approvals(self):
        activate("sess-1", "code-review")
        approve("sess-1", "code-review")
        clear_session("sess-1")
        assert not is_approved("sess-1", "code-review")
        assert not is_activated("sess-1", "code-review")

    def test_approval_independent_of_activation(self):
        """Approval and activation are tracked separately."""
        approve("sess-1", "code-review")
        assert is_approved("sess-1", "code-review")
        assert not is_activated("sess-1", "code-review")
