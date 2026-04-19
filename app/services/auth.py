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
if not settings.JWT_SECRET:
    _jwt_secret = secrets.token_hex(32)
    logger.warning(
        "JWT_SECRET not configured — using ephemeral secret. "
        "Tokens will be invalidated on server restart. Set JWT_SECRET in .env for persistence."
    )
else:
    _jwt_secret = settings.JWT_SECRET


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


# Short-lived tokens injected into interactive HTML widget iframes so their
# JS can call /api/v1/... as the bot that authored them — not as the
# viewing user. TTL is deliberately short so screenshots / devtools
# snapshots expire quickly; the renderer re-mints before expiry.
WIDGET_TOKEN_TTL_SECONDS = 900  # 15 minutes


def create_widget_token(
    *,
    bot_id: str,
    scopes: list[str],
    api_key_id: UUID,
    pin_id: UUID | str | None = None,
) -> tuple[str, datetime]:
    """Mint a short-lived widget bearer. ``kind: "widget"`` in the payload
    is how ``verify_auth_or_user`` tells this apart from a user JWT.

    Scopes are copied from the bot's own API key at mint time — not looked
    up again on each request — so revoking the bot's key doesn't
    immediately invalidate in-flight widget tokens (they expire on their
    own within ``WIDGET_TOKEN_TTL_SECONDS``). Acceptable trade-off for
    simpler verification.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=WIDGET_TOKEN_TTL_SECONDS)
    payload = {
        "kind": "widget",
        "sub": bot_id,
        "bot_id": bot_id,
        "scopes": list(scopes),
        "api_key_id": str(api_key_id),
        "iat": now,
        "exp": expires_at,
    }
    if pin_id is not None:
        payload["pin_id"] = str(pin_id)
    return jwt.encode(payload, _jwt_secret, algorithm="HS256"), expires_at


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
    await _provision_user_api_key(db, user)
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
    await _provision_user_api_key(db, user)
    return user


async def ensure_user_api_key(db: AsyncSession, user: User) -> None:
    """Ensure a user has an API key. Called on login for backward compat."""
    if user.api_key_id:
        return
    await _provision_user_api_key(db, user)


async def resolve_user_scopes(db: AsyncSession, user: User) -> list[str]:
    """Return the user's effective scopes for /auth/me hydration.

    Admins with a missing/inactive key get a synthetic ["admin"] so the UI
    still renders the admin surface even if their provisioning broke —
    matches the is_admin bypass in require_scopes().
    """
    if user.api_key_id:
        from app.db.models import ApiKey
        key = await db.get(ApiKey, user.api_key_id)
        if key is not None and key.is_active:
            return list(key.scopes or [])
    return ["admin"] if user.is_admin else []


async def _provision_user_api_key(db: AsyncSession, user: User) -> None:
    """Provision a scoped API key for a user based on their role."""
    try:
        from app.services.api_keys import ensure_entity_api_key, SCOPE_PRESETS

        preset_name = "admin_user" if user.is_admin else "member_user"
        scopes = SCOPE_PRESETS[preset_name]["scopes"]

        key, _full_value = await ensure_entity_api_key(
            db,
            name=f"user:{user.email}",
            scopes=scopes,
            existing_key_id=user.api_key_id,
        )
        if not user.api_key_id:
            user.api_key_id = key.id
            await db.commit()
            await db.refresh(user)
        logger.debug("Provisioned API key for user %s (preset=%s)", user.email, preset_name)
    except Exception:
        logger.warning("Failed to provision API key for user %s", user.email, exc_info=True)
