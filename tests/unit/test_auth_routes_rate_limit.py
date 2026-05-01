"""Auth-route rate limit parity.

``/auth/login`` and ``/auth/setup`` have always been per-IP throttled.
``/auth/google`` and ``/auth/refresh`` previously were not, leaving them
open to credential / token brute force from a single IP. These tests pin
the parity so the limits don't silently regress.
"""
from __future__ import annotations

import inspect

from app.routers import auth as auth_router


def _has_rate_limit_call(fn) -> bool:
    """Heuristic: source of the route function references ``_check_rate_limit``."""
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        return False
    return "_check_rate_limit(" in src


def test_login_is_rate_limited():
    assert _has_rate_limit_call(auth_router.auth_login)


def test_setup_is_rate_limited():
    assert _has_rate_limit_call(auth_router.auth_setup)


def test_google_is_rate_limited():
    """Google OAuth code exchange was an unguarded brute-force surface."""
    assert _has_rate_limit_call(auth_router.auth_google)


def test_refresh_is_rate_limited():
    """Refresh-token presentation was an unguarded brute-force surface."""
    assert _has_rate_limit_call(auth_router.auth_refresh)


def test_rate_limit_returns_429_after_threshold():
    """Direct exercise of the helper — the smoking gun behavior is preserved."""
    from fastapi import HTTPException

    auth_router._LOGIN_ATTEMPTS.clear()

    class _FakeReq:
        class client:
            host = "10.20.30.40"

    # First N-1 calls succeed, Nth fails
    for _ in range(auth_router._MAX_ATTEMPTS):
        auth_router._check_rate_limit(_FakeReq())

    try:
        auth_router._check_rate_limit(_FakeReq())
    except HTTPException as exc:
        assert exc.status_code == 429
    else:  # pragma: no cover - assertion guard
        raise AssertionError("Expected HTTPException 429 after threshold")
