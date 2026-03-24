"""User authentication service — JWT, password hashing, Google OAuth."""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import bcrypt
import httpx
import jwt
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import RefreshToken, User

logger = logging.getLogger(__name__)

_http = httpx.AsyncClient(timeout=15.0)

# Auto-generate JWT secret on first import if not configured
_jwt_secret: str = settings.JWT_SECRET or secrets.token_hex(32)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "is_admin": user.is_admin,
        "iat": now,
        "exp": now + timedelta(seconds=settings.JWT_ACCESS_EXPIRY),
    }
    return jwt.encode(payload, _jwt_secret, algorithm="HS256")


async def create_refresh_token(user: User, db: AsyncSession) -> str:
    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.JWT_REFRESH_EXPIRY)

    db.add(RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    ))
    await db.commit()
    return raw_token


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token. Raises jwt.InvalidTokenError on failure."""
    return jwt.decode(token, _jwt_secret, algorithms=["HS256"])


async def validate_refresh_token(raw_token: str, db: AsyncSession) -> RefreshToken | None:
    """Look up a refresh token by hash and check expiry. Returns the row or None."""
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    stmt = select(RefreshToken).where(
        RefreshToken.token_hash == token_hash,
        RefreshToken.expires_at > datetime.now(timezone.utc),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def revoke_refresh_token(raw_token: str, db: AsyncSession) -> None:
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------

async def exchange_google_code(code: str, redirect_uri: str) -> dict:
    """Exchange a Google auth code for user info. Returns {email, name, picture}."""
    # Step 1: exchange code for tokens
    token_resp = await _http.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    token_resp.raise_for_status()
    tokens = token_resp.json()

    # Step 2: get user info
    userinfo_resp = await _http.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    userinfo_resp.raise_for_status()
    info = userinfo_resp.json()

    return {
        "email": info["email"],
        "name": info.get("name", info["email"].split("@")[0]),
        "picture": info.get("picture"),
    }


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

async def is_setup_required(db: AsyncSession) -> bool:
    result = await db.execute(select(func.count(User.id)))
    return result.scalar_one() == 0


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: UUID) -> User | None:
    return await db.get(User, user_id)


async def create_local_user(
    db: AsyncSession,
    email: str,
    display_name: str,
    password: str,
    is_admin: bool = False,
) -> User:
    user = User(
        email=email,
        display_name=display_name,
        password_hash=hash_password(password),
        auth_method="local",
        is_admin=is_admin,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_or_create_google_user(
    db: AsyncSession,
    email: str,
    name: str,
    picture: str | None,
    is_admin: bool = False,
) -> User:
    user = await get_user_by_email(db, email)
    if user:
        return user

    user = User(
        email=email,
        display_name=name,
        avatar_url=picture,
        auth_method="google",
        is_admin=is_admin,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
