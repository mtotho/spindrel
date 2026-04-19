"""Phase H.2 — auth.py::_provision_user_api_key exception swallow.

Seam class: partial-commit (exception swallowed, user created without API key)

``_provision_user_api_key()`` wraps the entire key-provisioning call in
``try/except Exception``. If ``ensure_entity_api_key`` fails partway (DB error,
IntegrationSetting upsert fails after ApiKey commit), the exception is logged as
a warning and the function returns cleanly. The caller (``create_local_user``,
``get_or_create_google_user``) returns the user row regardless — user can log in
but ``user.api_key_id is None``, causing 403 on every scoped API call.

Contracts pinned:
1. Happy path: user created → api_key_id set on user row.
2. Provisioning failure: user created but api_key_id stays None; no exception raised.
3. ``ensure_user_api_key`` idempotent guard: skips re-provision when key exists.
4. ``ensure_user_api_key`` re-provision: called on orphaned user → sets api_key_id.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.db.models import ApiKey, User
from app.services.auth import (
    create_local_user,
    ensure_user_api_key,
    _provision_user_api_key,
)


# ---------------------------------------------------------------------------
# H.2.1 — happy path: user + key created
# ---------------------------------------------------------------------------


class TestProvisionHappyPath:
    @pytest.mark.asyncio
    async def test_when_user_created_then_api_key_id_set(self, db_session):
        user = await create_local_user(
            db_session, "happy@example.com", "Happy", "pw123"
        )
        await db_session.refresh(user)
        assert user.api_key_id is not None

        # The ApiKey row must exist.
        key = await db_session.get(ApiKey, user.api_key_id)
        assert key is not None
        assert key.is_active is True

    @pytest.mark.asyncio
    async def test_when_admin_user_created_then_api_key_has_admin_scopes(
        self, db_session
    ):
        user = await create_local_user(
            db_session, "admin@example.com", "Admin", "pw123", is_admin=True
        )
        await db_session.refresh(user)
        key = await db_session.get(ApiKey, user.api_key_id)
        assert key is not None
        # Admin keys should carry an admin-level scope.
        assert any("admin" in (s or "") for s in (key.scopes or []))


# ---------------------------------------------------------------------------
# H.2.2 — drift pin: exception swallow creates orphaned user
# ---------------------------------------------------------------------------


class TestProvisioningFailureDrift:
    @pytest.mark.asyncio
    async def test_when_provision_raises_then_user_created_but_api_key_id_is_none(
        self, db_session
    ):
        """Simulates ensure_entity_api_key failure (e.g. DB constraint mid-txn).

        The user row is committed before _provision_user_api_key is called, so
        on failure the user exists but has no scopes.  Warning is logged; no
        exception propagates to the caller.
        """
        with patch(
            "app.services.api_keys.ensure_entity_api_key",
            new_callable=AsyncMock,
            side_effect=RuntimeError("simulated DB failure"),
        ):
            user = await create_local_user(
                db_session, "orphan@example.com", "Orphan", "pw123"
            )

        await db_session.refresh(user)
        # User row was committed.
        assert user.id is not None
        # api_key_id was never set due to the exception.
        assert user.api_key_id is None

    @pytest.mark.asyncio
    async def test_when_provision_fails_then_no_exception_propagated(
        self, db_session
    ):
        """Caller must not receive an exception even when provisioning fails."""
        with patch(
            "app.services.api_keys.ensure_entity_api_key",
            new_callable=AsyncMock,
            side_effect=Exception("oops"),
        ):
            # Should not raise.
            user = await create_local_user(
                db_session, "safe@example.com", "Safe", "pw123"
            )
        assert user.email == "safe@example.com"


# ---------------------------------------------------------------------------
# H.2.3 — ensure_user_api_key idempotent guard
# ---------------------------------------------------------------------------


class TestEnsureUserApiKeyIdempotent:
    @pytest.mark.asyncio
    async def test_when_api_key_id_already_set_then_ensure_is_no_op(
        self, db_session
    ):
        """ensure_user_api_key skips provisioning if api_key_id already present."""
        user = await create_local_user(
            db_session, "existing@example.com", "Existing", "pw123"
        )
        await db_session.refresh(user)
        original_key_id = user.api_key_id
        assert original_key_id is not None

        # Call ensure again — must not create a new key.
        with patch(
            "app.services.api_keys.ensure_entity_api_key",
            new_callable=AsyncMock,
        ) as mock_eak:
            await ensure_user_api_key(db_session, user)
            mock_eak.assert_not_called()

        await db_session.refresh(user)
        assert user.api_key_id == original_key_id


# ---------------------------------------------------------------------------
# H.2.4 — orphan recovery: ensure re-provisions when api_key_id is None
# ---------------------------------------------------------------------------


class TestEnsureUserApiKeyRecovery:
    @pytest.mark.asyncio
    async def test_when_user_has_no_api_key_then_ensure_provisions_one(
        self, db_session
    ):
        """ensure_user_api_key re-provisions an orphaned user (api_key_id=None)."""
        # Create a user WITHOUT going through create_local_user so we get
        # a truly orphaned row.
        user = User(
            email="recover@example.com",
            display_name="Recover",
            password_hash="x",
            auth_method="local",
            is_admin=False,
            is_active=True,
            api_key_id=None,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        assert user.api_key_id is None

        await ensure_user_api_key(db_session, user)

        await db_session.refresh(user)
        assert user.api_key_id is not None
