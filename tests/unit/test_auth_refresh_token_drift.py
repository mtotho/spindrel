"""Phase H.1 — auth.py::revoke_refresh_token silent 0-row DELETE.

Seam class: silent-UPDATE (0-row DELETE with no signal to caller)

``revoke_refresh_token()`` looks up a RefreshToken by hash and deletes it if
found. If NOT found (expired or already revoked), the function returns cleanly
with no error and no return value — caller cannot distinguish "revoked" from
"already gone". Double-revoke succeeds twice without raising.

Contracts pinned:
1. Happy path: token created → revoked → row gone from DB.
2. Double-revoke: second call finds no row, returns cleanly (no error/exception).
3. Revoke non-existent hash: silent no-op.
4. Revoke then validate: ``validate_refresh_token`` returns None for revoked token.
"""
from __future__ import annotations

import pytest

from app.db.models import RefreshToken, User
from app.services.auth import (
    create_refresh_token,
    revoke_refresh_token,
    validate_refresh_token,
)


# ---------------------------------------------------------------------------
# Shared fixture: minimal User row (no API key required)
# ---------------------------------------------------------------------------


@pytest.fixture
async def _user(db_session):
    u = User(
        email="drift@example.com",
        display_name="Drift",
        password_hash="x",
        auth_method="local",
        is_admin=False,
        is_active=True,
    )
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


# ---------------------------------------------------------------------------
# H.1.1 — happy-path revocation
# ---------------------------------------------------------------------------


class TestRevokeHappyPath:
    @pytest.mark.asyncio
    async def test_when_valid_token_revoked_then_row_deleted(self, db_session, _user):
        raw = await create_refresh_token(_user, db_session)
        await revoke_refresh_token(raw, db_session)

        # Row must no longer exist.
        result = await validate_refresh_token(raw, db_session)
        assert result is None

    @pytest.mark.asyncio
    async def test_when_multiple_tokens_only_target_deleted(self, db_session, _user):
        """Revoking one token leaves siblings untouched."""
        raw_a = await create_refresh_token(_user, db_session)
        raw_b = await create_refresh_token(_user, db_session)

        await revoke_refresh_token(raw_a, db_session)

        assert await validate_refresh_token(raw_a, db_session) is None
        # raw_b must still validate.
        row_b = await validate_refresh_token(raw_b, db_session)
        assert row_b is not None
        assert row_b.user_id == _user.id


# ---------------------------------------------------------------------------
# H.1.2 — drift pin: double-revoke is silent
# ---------------------------------------------------------------------------


class TestDoubleRevoke:
    @pytest.mark.asyncio
    async def test_when_token_revoked_twice_then_second_call_is_silent(
        self, db_session, _user
    ):
        """No exception raised on the second revoke; 0-row DELETE is accepted.

        Pins the contract that callers cannot rely on revoke() to signal
        whether the token was actually present — it always succeeds.
        """
        raw = await create_refresh_token(_user, db_session)
        await revoke_refresh_token(raw, db_session)

        # Second call: should not raise even though the row is gone.
        await revoke_refresh_token(raw, db_session)

        # Row still absent.
        assert await validate_refresh_token(raw, db_session) is None


# ---------------------------------------------------------------------------
# H.1.3 — drift pin: revoke a token that was never created
# ---------------------------------------------------------------------------


class TestRevokeNonExistent:
    @pytest.mark.asyncio
    async def test_when_nonexistent_token_revoked_then_no_error(self, db_session):
        """Revoking a hash that was never inserted is a silent no-op.

        Pins the fire-and-forget contract: caller gets no feedback about
        whether the DELETE matched any rows.
        """
        await revoke_refresh_token("totally-fake-raw-token-that-never-existed", db_session)
        # Reaching here without exception is the assertion.
