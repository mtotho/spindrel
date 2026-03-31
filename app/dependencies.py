from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import async_session

logger = logging.getLogger(__name__)


@dataclass
class ApiKeyAuth:
    """Represents an authenticated scoped API key."""
    key_id: UUID
    scopes: list[str]
    name: str


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with async_session() as session:
        yield session


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
    db: AsyncSession = Depends(get_db),
):
    """Validate JWT access token. Returns the User ORM object."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.removeprefix("Bearer ")

    from app.services.auth import decode_access_token, get_user_by_id
    import jwt as _jwt

    try:
        payload = decode_access_token(token)
    except _jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = UUID(payload["sub"])
    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or deactivated")
    return user


async def verify_auth_or_user(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """Accept API key (static or scoped), or JWT.

    Returns:
    - str: static API key (full access)
    - ApiKeyAuth: scoped API key
    - User: JWT-authenticated user
    """
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

    user_id = UUID(payload["sub"])
    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or deactivated")
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

    user_id = UUID(payload["sub"])
    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
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


def require_scopes(*scopes: str):
    """Dependency factory that enforces scope requirements on API keys.

    JWT users always pass through (full access).
    ApiKeyAuth (including static env key) is checked against required scopes.
    The static env key and any key with 'admin' scope bypass all checks.
    """
    async def _check(
        auth=Depends(verify_auth_or_user),
    ):
        if not isinstance(auth, ApiKeyAuth):
            # User object from JWT → full access
            return auth
        # API key → check scopes
        from app.services.api_keys import has_scope
        for scope in scopes:
            if not has_scope(auth.scopes, scope):
                raise HTTPException(
                    status_code=403,
                    detail=f"Missing required scope: {scope}",
                )
        return auth
    return _check
