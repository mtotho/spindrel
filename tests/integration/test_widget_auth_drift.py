"""Phase Q-SEC-1 — Widget-auth drift-pin.

Complements ``test_widget_auth_mint.py`` (basic happy path + auth gate) and
``test_widget_auth_security.py`` (scope-ceiling, TTL, key-rotation, concurrency).

Drift seams pinned here:

QS.1  Token-payload claim shape — ``kind == "widget"`` (not "user"/"access"),
      ``sub == bot_id``, ``api_key_id`` matches the BOT's key (not caller's),
      ``jti`` present as UUID4, ``exp - iat == WIDGET_TOKEN_TTL_SECONDS`` exact.
QS.2  ``pin_id`` passthrough — present in body → present in token payload,
      absent from body → no ``pin_id`` claim (not empty-string, not null).
QS.3  Scope passthrough — bot scopes are copied VERBATIM (order, duplicates,
      case). Not filtered, not alphabetized, not deduped.
QS.4  Non-admin ApiKeyAuth caller — scoped API keys with non-admin scopes
      cannot mint. (_caller_may_use_bot returns False on non-User non-admin.)
QS.5  Dangling ``api_key_id`` — bot references an api_key row that doesn't
      exist (FK nullability gap) → 400 bot_api_key_inactive, NOT 500.
QS.6  Empty-scopes bot — mint succeeds with ``scopes=[]`` (not default-admin,
      not ["chat"] fallback).
QS.7  ``pin_id`` is not validated against bot ownership — any string accepted
      and stored in the token (passthrough contract; pin it so future owner
      knows it's intentional).
"""
from __future__ import annotations

import uuid
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.models import Bot, User

pytestmark = pytest.mark.asyncio


async def _make_bot_with_key(db_session, scopes: list[str], *, owner_id=None):
    from app.services.api_keys import create_api_key

    key, _ = await create_api_key(db_session, name="bot-key", scopes=scopes, store_key_value=True)
    bot = Bot(
        id=f"bot-{uuid.uuid4().hex[:8]}",
        name="Drift Bot",
        display_name="Drift Bot",
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
        email=f"d-{uuid.uuid4().hex[:6]}@test",
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


def _decode(token: str) -> dict:
    import jwt as _jwt
    from app.services.auth import _jwt_secret

    return _jwt.decode(token, _jwt_secret, algorithms=["HS256"])


# ===========================================================================
# QS.1 — Token payload claim shape
# ===========================================================================


class TestTokenClaimShape:
    async def test_kind_claim_is_literally_widget(self, client_factory, db_session):
        """``kind`` claim is exactly ``"widget"`` — never ``"user"`` / ``"access"``.
        verify_auth_or_user routes on this literal.
        """
        admin = await _make_user(db_session, is_admin=True)
        bot, _ = await _make_bot_with_key(db_session, ["chat"])
        app = client_factory(admin)

        resp = await _post_mint(app, {"source_bot_id": bot.id})
        assert resp.status_code == 200, resp.text
        payload = _decode(resp.json()["token"])
        assert payload["kind"] == "widget"

    async def test_sub_and_bot_id_both_carry_bot_id(self, client_factory, db_session):
        """Both ``sub`` and ``bot_id`` claims are populated with the bot's id.
        Some verify paths check one, some the other — pin symmetry.
        """
        admin = await _make_user(db_session, is_admin=True)
        bot, _ = await _make_bot_with_key(db_session, ["chat"])
        app = client_factory(admin)

        resp = await _post_mint(app, {"source_bot_id": bot.id})
        payload = _decode(resp.json()["token"])
        assert payload["sub"] == bot.id
        assert payload["bot_id"] == bot.id

    async def test_api_key_id_claim_matches_bot_key_not_caller(
        self, client_factory, db_session
    ):
        """``api_key_id`` claim is the BOT's API key, never the caller's.
        Critical: caller's admin scope must not leak via an api_key_id swap.
        """
        admin = await _make_user(db_session, is_admin=True)
        bot, bot_key = await _make_bot_with_key(db_session, ["chat"])
        app = client_factory(admin)

        resp = await _post_mint(app, {"source_bot_id": bot.id})
        payload = _decode(resp.json()["token"])
        assert payload["api_key_id"] == str(bot_key.id)

    async def test_jti_is_uuid4(self, client_factory, db_session):
        """``jti`` is a UUID4 string (Phase P nonce). Pin the type so a drift
        back to deterministic token output surfaces immediately.
        """
        admin = await _make_user(db_session, is_admin=True)
        bot, _ = await _make_bot_with_key(db_session, ["chat"])
        app = client_factory(admin)

        resp = await _post_mint(app, {"source_bot_id": bot.id})
        payload = _decode(resp.json()["token"])
        jti = payload["jti"]
        # UUID() raises ValueError on non-UUID string.
        UUID(jti)
        assert len(jti) == 36

    async def test_ttl_is_exactly_900_seconds(self, client_factory, db_session):
        """``exp - iat == WIDGET_TOKEN_TTL_SECONDS`` (900s).  If TTL changes,
        update both ``app.services.auth.WIDGET_TOKEN_TTL_SECONDS`` and this test.
        """
        from app.services.auth import WIDGET_TOKEN_TTL_SECONDS

        admin = await _make_user(db_session, is_admin=True)
        bot, _ = await _make_bot_with_key(db_session, ["chat"])
        app = client_factory(admin)

        resp = await _post_mint(app, {"source_bot_id": bot.id})
        payload = _decode(resp.json()["token"])
        # PyJWT decodes iat/exp to int timestamps.
        assert payload["exp"] - payload["iat"] == WIDGET_TOKEN_TTL_SECONDS


# ===========================================================================
# QS.2 — pin_id passthrough
# ===========================================================================


class TestPinIdClaim:
    async def test_pin_id_present_in_body_is_in_payload(self, client_factory, db_session):
        admin = await _make_user(db_session, is_admin=True)
        bot, _ = await _make_bot_with_key(db_session, ["chat"])
        app = client_factory(admin)

        pin_id = str(uuid.uuid4())
        resp = await _post_mint(app, {"source_bot_id": bot.id, "pin_id": pin_id})
        assert resp.status_code == 200, resp.text
        payload = _decode(resp.json()["token"])
        assert payload["pin_id"] == pin_id

    async def test_pin_id_absent_means_no_claim(self, client_factory, db_session):
        """No ``pin_id`` in body → the ``pin_id`` claim is absent from the token
        (not empty string, not null). verify_auth_or_user uses presence as a
        signal, not the string value.
        """
        admin = await _make_user(db_session, is_admin=True)
        bot, _ = await _make_bot_with_key(db_session, ["chat"])
        app = client_factory(admin)

        resp = await _post_mint(app, {"source_bot_id": bot.id})
        payload = _decode(resp.json()["token"])
        assert "pin_id" not in payload, (
            f"pin_id leaked as {payload.get('pin_id')!r} when omitted from body"
        )

    async def test_pin_id_is_passthrough_not_validated(self, client_factory, db_session):
        """The mint endpoint does NOT validate pin_id against ownership or
        existence — it's a passthrough claim. Pin the current contract so a
        future owner knows to add validation explicitly if desired.
        """
        admin = await _make_user(db_session, is_admin=True)
        bot, _ = await _make_bot_with_key(db_session, ["chat"])
        app = client_factory(admin)

        # An entirely synthetic pin_id that doesn't correspond to any pin row.
        fake_pin = "not-a-real-pin-id-at-all"
        resp = await _post_mint(app, {"source_bot_id": bot.id, "pin_id": fake_pin})
        assert resp.status_code == 200, resp.text
        payload = _decode(resp.json()["token"])
        assert payload["pin_id"] == fake_pin


# ===========================================================================
# QS.3 — Scope verbatim passthrough
# ===========================================================================


class TestScopePassthrough:
    async def test_multiple_scopes_preserved_verbatim(self, client_factory, db_session):
        """Bot scope list is copied EXACTLY to the token — no filtering,
        dedup, sort, case-change.  Verifies widget permission surface matches
        bot permission surface perfectly.
        """
        admin = await _make_user(db_session, is_admin=True)
        bot, _ = await _make_bot_with_key(
            db_session, ["chat", "attachments:read", "channels:read"]
        )
        app = client_factory(admin)

        resp = await _post_mint(app, {"source_bot_id": bot.id})
        payload = _decode(resp.json()["token"])
        # Preserve input order, don't mutate.
        assert payload["scopes"] == ["chat", "attachments:read", "channels:read"]

    async def test_empty_scopes_mints_successfully(self, client_factory, db_session):
        """Bot with empty scope list → mint succeeds with ``scopes=[]``.
        Not a 400; not a default-admin fallback.  Widget that gets this
        token can call nothing — matches the bot's permissions.
        """
        admin = await _make_user(db_session, is_admin=True)
        bot, _ = await _make_bot_with_key(db_session, [])
        app = client_factory(admin)

        resp = await _post_mint(app, {"source_bot_id": bot.id})
        assert resp.status_code == 200, resp.text
        payload = _decode(resp.json()["token"])
        assert payload["scopes"] == []


# ===========================================================================
# QS.4 — Non-admin ApiKeyAuth callers cannot mint
# ===========================================================================


class TestNonAdminApiKeyAuthCallerBlocked:
    async def test_tool_scoped_api_key_caller_403(self, client_factory, db_session):
        """ApiKeyAuth with scopes like ``["chat"]`` (no admin) → 403.
        ``_caller_may_use_bot`` returns False because caller is neither admin
        nor a ``User`` instance.
        """
        from app.dependencies import ApiKeyAuth

        tool_caller = ApiKeyAuth(
            key_id=uuid.uuid4(), scopes=["chat"], name="tool-key"
        )
        bot, _ = await _make_bot_with_key(db_session, ["chat"])
        app = client_factory(tool_caller)

        resp = await _post_mint(app, {"source_bot_id": bot.id})
        assert resp.status_code == 403, resp.text
        detail = resp.json()["detail"]
        assert detail["reason"] == "bot_access_denied"

    async def test_admin_scoped_api_key_caller_200(self, client_factory, db_session):
        """ApiKeyAuth with ``["admin"]`` scope → mint succeeds. ``_is_admin``
        recognizes admin-scoped keys. Pins the positive half of the gate.
        """
        from app.dependencies import ApiKeyAuth

        admin_key = ApiKeyAuth(
            key_id=uuid.uuid4(), scopes=["admin"], name="admin-key"
        )
        bot, _ = await _make_bot_with_key(db_session, ["chat"])
        app = client_factory(admin_key)

        resp = await _post_mint(app, {"source_bot_id": bot.id})
        assert resp.status_code == 200, resp.text


# ===========================================================================
# QS.5 — Dangling api_key_id FK gap
# ===========================================================================


class TestDanglingApiKeyId:
    async def test_bot_references_missing_api_key_row_returns_400(
        self, client_factory, db_session
    ):
        """Bot has ``api_key_id`` pointing at a row that doesn't exist
        (deleted without cascading).  Should 400 (bot_api_key_inactive),
        never 500.
        """
        admin = await _make_user(db_session, is_admin=True)
        bot, key = await _make_bot_with_key(db_session, ["chat"])
        # Delete the api_key row out from under the bot.
        await db_session.delete(key)
        await db_session.commit()

        app = client_factory(admin)
        resp = await _post_mint(app, {"source_bot_id": bot.id})
        assert resp.status_code == 400, resp.text
        detail = resp.json()["detail"]
        assert detail["reason"] == "bot_api_key_inactive"
        assert detail["bot_id"] == bot.id
