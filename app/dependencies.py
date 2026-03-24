from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import async_session

logger = logging.getLogger(__name__)


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
    """Accept either API key or JWT. Returns token string (API key) or User object (JWT)."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.removeprefix("Bearer ")

    # Try API key first (fast path)
    if token == settings.API_KEY:
        return token

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


async def optional_user(
    authorization: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Extract user from JWT if present, otherwise None. Never raises."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ")
    if token == settings.API_KEY:
        return None

    from app.services.auth import decode_access_token, get_user_by_id
    import jwt as _jwt

    try:
        payload = decode_access_token(token)
        user_id = UUID(payload["sub"])
        return await get_user_by_id(db, user_id)
    except Exception:
        return None
