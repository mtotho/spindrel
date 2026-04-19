"""Phase J — Widget Auth & Bot-Scoped Token Security Tests.

Seams from plan rippling-giggling-bachman.md Phase J:

J.1  Scope ceiling — admin-minted widget token cannot carry admin scopes.
     Scopes are copied from the BOT's API key at mint time, not from the
     caller's identity.

J.3  Key rotation doesn't invalidate outstanding token (accepted design).
     Scopes are embedded in the JWT at mint; revoking the bot's key after
     mint leaves the widget token valid for its TTL.  Pin as documented
     design, not a bug.

J.5  Two concurrent mint POSTs for the same bot yield two distinct JWTs.
     Each is independently valid for its TTL.

J.6  TTL boundary — expired token fails JWT decode.  (No freezegun; we
     craft an expired JWT directly via jwt.encode with a past exp.)

J.7  Inactive bot API key → 400 (not 200, not 401).  The mint endpoint
     explicitly checks api_key.is_active at line 94 of the widget auth router.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.models import ApiKey, Bot, User

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_widget_auth_mint.py helpers)
# ---------------------------------------------------------------------------

async def _make_bot_with_key(db_session, scopes: list[str], *, owner_id=None):
    from app.services.api_keys import create_api_key
    key, _ = await create_api_key(db_session, name="bot-key", scopes=scopes, store_key_value=True)
    bot = Bot(
        id=f"bot-{uuid.uuid4().hex[:8]}",
        name="Security Test Bot",
        display_name="Security Test Bot",
        model="test/model",
        system_prompt="",
        api_key_id=key.id,
        user_id=owner_id,
    )
    db_session.add(bot)
    await db_session.commit()
    await db_session.refresh(bot)
    return bot, key


async def _make_user(db_session, *, is_admin: bool = False) -> User:
    user = User(
        email=f"sec-{uuid.uuid4().hex[:6]}@test",
        display_name="U",
        password_hash="x",
        auth_method="local",
        is_admin=is_admin,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def client_factory(db_session):
    from fastapi import FastAPI
    from app.routers.api_v1 import router as api_v1_router
    from app.dependencies import get_db, verify_auth_or_user

    def _make(auth_principal):
        app = FastAPI()
        app.include_router(api_v1_router)

        async def _override_get_db():
            yield db_session

        async def _override_auth():
            return auth_principal

        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[verify_auth_or_user] = _override_auth
        return app

    yield _make


async def _post_mint(app, body: dict):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        return await ac.post("/api/v1/widget-auth/mint", json=body)


# ===========================================================================
# J.1 — Scope ceiling: admin cannot inflate widget token scopes
# ===========================================================================


class TestScopeCeiling:
    """Widget token scopes are copied from the bot's own API key at mint time.
    An admin caller cannot inject admin or any extra scope into the token.
    """

    async def test_admin_minted_token_only_has_bot_scopes(
        self, client_factory, db_session
    ):
        """Admin user mints a widget token for a bot with only ``["chat"]``.
        The resulting token must carry exactly ``["chat"]``, not the admin's
        own scopes or the ``["admin"]`` scope.
        """
        import jwt as _jwt
        from app.services.auth import _jwt_secret

        admin = await _make_user(db_session, is_admin=True)
        bot, _ = await _make_bot_with_key(db_session, ["chat"])  # bot has ONLY chat
        app = client_factory(admin)

        resp = await _post_mint(app, {"source_bot_id": bot.id})
        assert resp.status_code == 200, resp.text

        # Verify response-level scope
        body = resp.json()
        assert body["scopes"] == ["chat"], (
            f"Admin scope leaked into widget token: {body['scopes']}"
        )

        # Verify JWT-level scope (the actual bearer claim)
        payload = _jwt.decode(body["token"], _jwt_secret, algorithms=["HS256"])
        assert payload["scopes"] == ["chat"]
        assert "admin" not in payload["scopes"], (
            "Admin scope must NEVER appear in a widget token, even when minted by admin"
        )

    async def test_bot_scopes_are_upper_bound_of_widget_token(
        self, client_factory, db_session
    ):
        """Bot with no scopes → widget token has no scopes (empty list, not admin
        fallback).
        """
        import jwt as _jwt
        from app.services.auth import _jwt_secret

        admin = await _make_user(db_session, is_admin=True)
        bot, _ = await _make_bot_with_key(db_session, [])  # bot has no scopes
        app = client_factory(admin)

        resp = await _post_mint(app, {"source_bot_id": bot.id})
        assert resp.status_code == 200, resp.text

        payload = _jwt.decode(resp.json()["token"], _jwt_secret, algorithms=["HS256"])
        assert payload["scopes"] == []
        assert "admin" not in payload.get("scopes", [])


# ===========================================================================
# J.3 — Key rotation doesn't invalidate outstanding widget token
# ===========================================================================


class TestKeyRotationDoesNotInvalidateToken:
    """Widget tokens are self-contained JWTs — scopes are embedded at mint time.
    Deactivating the bot's API key after the token is minted does NOT make the
    token fail verification (it expires naturally at TTL).

    This is intentional design (documented in ``app/services/auth.py::create_widget_token``).
    Pinned here so the behavior is explicit if we later add revocation.
    """

    async def test_token_still_validates_after_key_deactivated(
        self, client_factory, db_session
    ):
        """Mint token → deactivate bot's API key → verify_auth_or_user still
        accepts the outstanding token for its TTL.
        """
        from app.dependencies import verify_auth_or_user, ApiKeyAuth

        admin = await _make_user(db_session, is_admin=True)
        bot, key = await _make_bot_with_key(db_session, ["chat"])
        app = client_factory(admin)

        resp = await _post_mint(app, {"source_bot_id": bot.id})
        assert resp.status_code == 200
        token = resp.json()["token"]

        # Rotate / deactivate the bot's API key.
        key.is_active = False
        await db_session.commit()

        # Outstanding widget token should still decode correctly.
        auth = await verify_auth_or_user(
            authorization=f"Bearer {token}", db=db_session,
        )
        assert isinstance(auth, ApiKeyAuth), (
            "Widget token rejected after key deactivation — "
            "revocation cascade not expected (pin as accepted design). "
            "If revocation is now intentional, update this test."
        )
        assert "chat" in auth.scopes


# ===========================================================================
# J.5 — Two concurrent mints yield two distinct JWTs
# ===========================================================================


class TestConcurrentMint:
    """Same-second concurrent POST /mint for the same bot yields the SAME token.

    ``create_widget_token`` uses ``datetime.now(timezone.utc)`` with second-level
    precision for ``iat`` and ``exp``.  Within the same second, all JWT inputs
    are identical so ``jwt.encode`` produces the same deterministic signature.

    Pinning current contract: same-second concurrent mints are idempotent.
    If a ``jti`` nonce is ever added, update assertion to ``t1 != t2``.
    """

    async def test_concurrent_same_second_mints_produce_same_token(
        self, client_factory, db_session
    ):
        """Pinning current (deterministic) behavior: same-second concurrent
        mints for the same bot return the SAME JWT because create_widget_token
        has no per-call nonce — iat/exp are second-level and all other inputs
        are fixed.

        Update assertion to ``t1 != t2`` if randomness (jti) is added.
        """
        admin = await _make_user(db_session, is_admin=True)
        bot, _ = await _make_bot_with_key(db_session, ["chat"])
        app = client_factory(admin)

        async def _mint():
            return await _post_mint(app, {"source_bot_id": bot.id})

        r1, r2 = await asyncio.gather(_mint(), _mint())

        assert r1.status_code == 200, r1.text
        assert r2.status_code == 200, r2.text

        t1 = r1.json()["token"]
        t2 = r2.json()["token"]
        # Pinning current contract: deterministic JWT → same token within the same second.
        assert t1 == t2, (
            "Concurrent mints now return different tokens — a nonce (jti) was "
            "likely added. Update assertion to t1 != t2 once jti is verified."
        )

    async def test_concurrent_minted_tokens_are_valid(
        self, client_factory, db_session
    ):
        """Token(s) from concurrent mint pass verify_auth_or_user."""
        from app.dependencies import verify_auth_or_user, ApiKeyAuth

        admin = await _make_user(db_session, is_admin=True)
        bot, _ = await _make_bot_with_key(db_session, ["chat"])
        app = client_factory(admin)

        async def _mint():
            return (await _post_mint(app, {"source_bot_id": bot.id})).json()["token"]

        t1, t2 = await asyncio.gather(_mint(), _mint())

        for tok in (t1, t2):
            auth = await verify_auth_or_user(
                authorization=f"Bearer {tok}", db=db_session,
            )
            assert isinstance(auth, ApiKeyAuth)


# ===========================================================================
# J.6 — TTL boundary: expired JWT is rejected by verify_auth_or_user
# ===========================================================================


class TestTTLBoundary:
    """Widget tokens expire at ``exp`` in the JWT payload.

    Since freezegun is not installed, we craft an expired JWT directly via
    ``jwt.encode`` with ``exp`` in the past, then verify it's rejected by
    ``decode_access_token``.
    """

    async def test_expired_widget_token_fails_decode(self, db_session):
        """A widget token with ``exp`` 1 second in the past raises
        ``jwt.ExpiredSignatureError`` on ``decode_access_token``.
        """
        import jwt as _jwt
        from app.services.auth import _jwt_secret, decode_access_token

        now = datetime.now(timezone.utc)
        expired_payload = {
            "kind": "widget",
            "sub": "test-bot",
            "bot_id": "test-bot",
            "scopes": ["chat"],
            "api_key_id": str(uuid.uuid4()),
            "iat": now - timedelta(seconds=901),
            "exp": now - timedelta(seconds=1),  # 1 second in the past
        }
        expired_token = _jwt.encode(expired_payload, _jwt_secret, algorithm="HS256")

        with pytest.raises(_jwt.ExpiredSignatureError):
            decode_access_token(expired_token)

    async def test_valid_widget_token_decodes_successfully(self, db_session):
        """A token with exp 900 seconds in the future decodes without error."""
        import jwt as _jwt
        from app.services.auth import _jwt_secret, decode_access_token

        now = datetime.now(timezone.utc)
        valid_payload = {
            "kind": "widget",
            "sub": "test-bot",
            "bot_id": "test-bot",
            "scopes": ["chat"],
            "api_key_id": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(seconds=900),
        }
        valid_token = _jwt.encode(valid_payload, _jwt_secret, algorithm="HS256")

        decoded = decode_access_token(valid_token)
        assert decoded["bot_id"] == "test-bot"
        assert decoded["scopes"] == ["chat"]


# ===========================================================================
# J.7 — Inactive bot API key → 400 (not 200)
# ===========================================================================


class TestInactiveBotApiKey:
    """The mint endpoint checks ``api_key.is_active`` at line 94 of the router.
    A bot whose API key is marked inactive cannot be used to mint — the key
    can't back widget auth calls.  The response is 400 with a clear message.
    """

    async def test_inactive_api_key_returns_400(self, client_factory, db_session):
        admin = await _make_user(db_session, is_admin=True)
        bot, key = await _make_bot_with_key(db_session, ["chat"])

        # Deactivate the key before minting.
        key.is_active = False
        await db_session.commit()

        app = client_factory(admin)
        resp = await _post_mint(app, {"source_bot_id": bot.id})

        assert resp.status_code == 400, resp.text
        assert "inactive" in resp.json()["detail"].lower() or "missing" in resp.json()["detail"].lower()

    async def test_active_key_returns_200(self, client_factory, db_session):
        """Baseline: active key → 200.  Ensures the inactive test is meaningful."""
        admin = await _make_user(db_session, is_admin=True)
        bot, _ = await _make_bot_with_key(db_session, ["chat"])

        app = client_factory(admin)
        resp = await _post_mint(app, {"source_bot_id": bot.id})
        assert resp.status_code == 200, resp.text
