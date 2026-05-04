from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from uuid import UUID

from typing import Optional

from fastapi import Depends, HTTPException, Header
from sqlalchemy.exc import DBAPIError, InterfaceError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import async_session

logger = logging.getLogger(__name__)


@dataclass
class ApiKeyAuth:
    """Represents an authenticated scoped API key.

    ``pin_id`` is set only for widget-minted JWTs (``kind: "widget"``) and
    carries the dashboard pin the widget lives on. Endpoints that want to
    grant implicit channel-scoped access to a widget without requiring
    ``channels:read`` on the bot's API key can resolve the pin's dashboard
    and compare its slug against the requested channel.
    """
    key_id: UUID
    scopes: list[str]
    name: str
    pin_id: UUID | None = None


def _is_closed_connection_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "underlying connection is closed" in text
        or "connection is closed" in text
        or "connection was closed" in text
    )


async def _invalidate_after_closed_connection(session: AsyncSession, exc: BaseException) -> None:
    logger.warning(
        "DB session cleanup hit an already-closed connection; invalidating session",
        exc_info=exc,
    )
    try:
        await session.invalidate()
    except Exception:
        logger.debug("DB session invalidation after closed connection failed", exc_info=True)


async def release_db_read_transaction(session: AsyncSession, *, context: str) -> None:
    """End a request read transaction before response serialization/streaming.

    SQLAlchemy autobegins a transaction for SELECTs. Leaving that transaction
    open until FastAPI's dependency cleanup can trip Postgres'
    idle-in-transaction timeout on large or backpressured responses.
    """
    if not session.in_transaction():
        return
    try:
        await session.rollback()
    except (InterfaceError, DBAPIError) as exc:
        if _is_closed_connection_error(exc):
            logger.warning(
                "DB read transaction rollback failed after %s because the connection "
                "was already closed",
                context,
                exc_info=exc,
            )
            await _invalidate_after_closed_connection(session, exc)
            return
        raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    session = async_session()
    try:
        yield session
    finally:
        try:
            await session.close()
        except (InterfaceError, DBAPIError) as exc:
            if _is_closed_connection_error(exc):
                await _invalidate_after_closed_connection(session, exc)
            else:
                raise


async def verify_auth(authorization: str = Header(...)) -> str:
    """Validate static API key. Returns the token string."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.removeprefix("Bearer ")
    if token != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return token


async def verify_user(
    authorization: str = Header(...),
):
    """Validate JWT access token. Returns the User ORM object.

    Owns its own short-lived DB session and closes it before returning. This
    is critical for streaming routes (SSE): if `verify_user` depended on
    `get_db()`, FastAPI would keep that session alive for the entire request
    lifetime — for an SSE stream, that's hours, and Postgres reports the
    auth-lookup transaction as `idle in transaction` the whole time, eating
    a connection-pool slot per active stream.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.removeprefix("Bearer ")

    from app.services.auth import decode_access_token, get_user_by_id
    import jwt as _jwt

    try:
        payload = decode_access_token(token)
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if payload.get("kind") == "widget":
        raise HTTPException(status_code=401, detail="Widget tokens cannot authenticate as a user")

    try:
        user_id = UUID(payload["sub"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token subject")

    async with async_session() as db:
        user = await get_user_by_id(db, user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="User not found or deactivated")
        # Detach so callers can read attributes after the session closes.
        db.expunge(user)
    return user


async def verify_auth_or_user(
    authorization: Optional[str] = Header(None),
):
    """Accept API key (static or scoped), or JWT.

    Owns its own short-lived DB session — see `verify_user` for why this is
    critical for SSE routes. SSE handlers that depended on a generator-style
    `Depends(get_db)` would pin a connection in `idle in transaction` for
    the lifetime of the stream and exhaust the pool.

    Returns:
    - str: static API key (full access)
    - ApiKeyAuth: scoped API key
    - User: JWT-authenticated user
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.removeprefix("Bearer ")

    # Try static API key first (fast path) — treat as admin-scoped key
    if token == settings.API_KEY:
        return ApiKeyAuth(
            key_id=UUID("00000000-0000-0000-0000-000000000000"),
            scopes=["admin"],
            name="static-env-key",
        )

    # Try scoped API key (ask_ prefix)
    if token.startswith("ask_"):
        from app.services.api_keys import validate_api_key
        async with async_session() as db:
            api_key = await validate_api_key(db, token)
            if api_key is None:
                raise HTTPException(status_code=401, detail="Invalid or expired API key")
            return ApiKeyAuth(key_id=api_key.id, scopes=api_key.scopes or [], name=api_key.name)

    # Try JWT
    from app.services.auth import decode_access_token, get_user_by_id
    import jwt as _jwt

    try:
        payload = decode_access_token(token)
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid API key or token")

    # Widget-scoped JWTs (minted by POST /api/v1/widget-auth/mint) authenticate
    # interactive HTML widget iframes as the bot that authored them. They carry
    # the bot's scopes inline so we don't need a DB round-trip per request.
    if payload.get("kind") == "widget":
        bot_id = payload.get("bot_id") or payload.get("sub")
        scopes = payload.get("scopes") or []
        api_key_id_raw = payload.get("api_key_id")
        try:
            key_id = UUID(api_key_id_raw) if api_key_id_raw else UUID("00000000-0000-0000-0000-000000000000")
        except (TypeError, ValueError):
            raise HTTPException(status_code=401, detail="Invalid widget token")
        if not bot_id:
            raise HTTPException(status_code=401, detail="Invalid widget token")
        # Revocation check — admins kill compromised tokens via
        # POST /api/v1/admin/widgets/tokens/revoke. The JWT itself is
        # still cryptographically valid; revocation is a side-band veto.
        jti = payload.get("jti")
        if jti:
            from app.services.widget_token_revocations import is_revoked

            async with async_session() as db:
                if await is_revoked(db, api_key_id=key_id, jti=jti):
                    raise HTTPException(status_code=401, detail="Widget token revoked")
        pin_id_raw = payload.get("pin_id")
        try:
            pin_id = UUID(pin_id_raw) if pin_id_raw else None
        except (TypeError, ValueError):
            pin_id = None
        return ApiKeyAuth(
            key_id=key_id,
            scopes=list(scopes),
            name=f"widget:{bot_id}",
            pin_id=pin_id,
        )

    try:
        user_id = UUID(payload["sub"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token subject")

    async with async_session() as db:
        user = await get_user_by_id(db, user_id)
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="User not found or deactivated")

        # Eagerly resolve user's API key scopes (avoids extra DB round-trip in require_scopes)
        if user.api_key_id:
            from app.db.models import ApiKey
            api_key = await db.get(ApiKey, user.api_key_id)
            user._resolved_scopes = api_key.scopes if api_key and api_key.is_active else None
        else:
            user._resolved_scopes = None
        db.expunge(user)
    return user


async def verify_admin_auth(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """Validate admin access. When ADMIN_API_KEY is set, only that key (or valid JWT) is accepted.
    When empty, falls back to accepting API_KEY or JWT (backward compat).
    Scoped API keys with any scope are authenticated here; endpoint-level
    require_scopes() handles fine-grained authorization."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.removeprefix("Bearer ")

    _static_admin = ApiKeyAuth(
        key_id=UUID("00000000-0000-0000-0000-000000000000"),
        scopes=["admin"],
        name="static-env-key",
    )

    # If ADMIN_API_KEY is configured, check it first
    if settings.ADMIN_API_KEY:
        if token == settings.ADMIN_API_KEY:
            return _static_admin
        # Regular API_KEY is NOT accepted for admin routes when ADMIN_API_KEY is set
    else:
        # Backward compat: accept regular API_KEY
        if token == settings.API_KEY:
            return _static_admin

    # Try scoped API key — authenticate here, authorize at endpoint level via require_scopes()
    if token.startswith("ask_"):
        from app.services.api_keys import validate_api_key
        api_key = await validate_api_key(db, token)
        if api_key and (api_key.scopes or []):
            return ApiKeyAuth(key_id=api_key.id, scopes=api_key.scopes or [], name=api_key.name)
        raise HTTPException(status_code=403, detail="Admin access denied")

    # Try JWT
    from app.services.auth import decode_access_token, get_user_by_id
    import jwt as _jwt

    try:
        payload = decode_access_token(token)
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    # Widget-kind JWTs carry a bot_id in `sub`, not a user UUID. They authenticate
    # interactive HTML widget iframes as the emitting bot — a strictly narrower
    # surface than the admin API. Reject cleanly rather than crash on UUID parse.
    if payload.get("kind") == "widget":
        raise HTTPException(status_code=401, detail="Widget tokens cannot access admin endpoints")

    try:
        user_id = UUID(payload["sub"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token subject")
    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="Admin access denied")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access denied")
    return user


async def optional_user(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Extract user from JWT if present, otherwise None. Never raises."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ")
    # Static key and scoped API keys are not users
    if token == settings.API_KEY or token.startswith("ask_"):
        return None

    from app.services.auth import decode_access_token, get_user_by_id
    import jwt as _jwt

    try:
        payload = decode_access_token(token)
        user_id = UUID(payload["sub"])
        return await get_user_by_id(db, user_id)
    except Exception:
        return None


def assert_admin_or_channel_owner(channel, auth) -> None:
    """Raise 403 unless ``auth`` is admin-equivalent or owns ``channel``.

    - ``ApiKeyAuth`` (any scope) is admin-equivalent here: scoped API keys are
      not users and have no ownership concept; row-level access for keys is
      gated by the scope check at the dependency layer.
    - JWT users pass when ``is_admin`` is true OR ``channel.user_id == user.id``.
    - Channels with no owner (``channel.user_id is None``) are admin-only edits.
    """
    if isinstance(auth, ApiKeyAuth):
        return
    if getattr(auth, "is_admin", False):
        return
    user_id = getattr(auth, "id", None)
    if channel.user_id is not None and user_id is not None and channel.user_id == user_id:
        return
    raise HTTPException(
        status_code=403,
        detail="Channel owner or admin access required",
    )


def require_admin_and_scope(scope: str):
    """Dependency factory that enforces a scope **and** admin-equivalence.

    Use for endpoints whose scope is technically reachable from a non-admin
    preset via ``has_scope`` parent-covers-child semantics (e.g.
    ``channels:write`` covers ``channels.integrations:write``) but which must
    remain admin-only. Rather than tightening ``has_scope`` globally (which
    would affect every ``*:*`` preset), this narrowly asserts that the caller
    is an admin on top of the normal scope check.

    Pass criteria:
    - ``ApiKeyAuth`` must include the literal ``"admin"`` scope (static env
      key and admin-user keys qualify; bot/integration presets do not).
    - JWT ``User`` must have ``is_admin=True``.
    - Widget-kind tokens never pass (they ride as ``ApiKeyAuth`` with the
      emitting bot's scopes, which do not include ``"admin"``).
    """
    async def _check(
        auth=Depends(require_scopes(scope)),
    ):
        if isinstance(auth, ApiKeyAuth):
            if "admin" in (auth.scopes or []):
                return auth
            raise HTTPException(status_code=403, detail="Admin access required")
        if getattr(auth, "is_admin", False):
            return auth
        raise HTTPException(status_code=403, detail="Admin access required")
    return _check


def require_scopes(*scopes: str):
    """Dependency factory that enforces scope requirements on API keys and users.

    ApiKeyAuth (including static env key) is checked against required scopes.
    JWT users with a provisioned API key are checked against that key's scopes.
    JWT users whose provisioning silently failed fail closed — except admins,
    who bypass via is_admin so they can recover. The static env key and any
    key/user with 'admin' scope bypass all checks.
    """
    async def _check(
        auth=Depends(verify_auth_or_user),
    ):
        from app.services.api_keys import has_scope
        if not isinstance(auth, ApiKeyAuth):
            resolved = getattr(auth, "_resolved_scopes", None)
            if resolved is None:
                # No active API key resolved. Admin users keep access via the
                # is_admin flag (so a broken provisioning doesn't lock the
                # only admin out); non-admins fail closed because the UI will
                # correctly render "no permissions" for them and the backend
                # must match.
                if getattr(auth, "is_admin", False):
                    return auth
                raise HTTPException(
                    status_code=403,
                    detail=f"Missing required scope: {scopes[0] if scopes else ''}",
                )
            for scope in scopes:
                if not has_scope(resolved, scope):
                    raise HTTPException(
                        status_code=403,
                        detail=f"Missing required scope: {scope}",
                    )
            return auth
        for scope in scopes:
            if not has_scope(auth.scopes, scope):
                raise HTTPException(
                    status_code=403,
                    detail=f"Missing required scope: {scope}",
                )
        return auth
    return _check
