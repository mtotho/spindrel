"""User authentication endpoints — setup, login, Google OAuth, token refresh."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_user
from app.services.auth import (
    create_access_token,
    create_refresh_token,
    create_local_user,
    exchange_google_code,
    get_or_create_google_user,
    get_user_by_email,
    get_user_by_id,
    is_setup_required,
    revoke_refresh_token,
    validate_refresh_token,
    verify_password,
)
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class AuthStatusResponse(BaseModel):
    setup_required: bool
    google_enabled: bool


class SetupRequest(BaseModel):
    method: str  # "local" | "google"
    email: str | None = None
    display_name: str | None = None
    password: str | None = None
    code: str | None = None  # Google auth code
    redirect_uri: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


class GoogleAuthRequest(BaseModel):
    code: str
    redirect_uri: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_url: str | None
    integration_config: dict
    is_admin: bool
    auth_method: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: UserResponse


class AccessTokenResponse(BaseModel):
    access_token: str


class UpdateProfileRequest(BaseModel):
    display_name: str | None = None
    avatar_url: str | None = None
    integration_config: dict | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


def _user_response(user) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        integration_config=user.integration_config or {},
        is_admin=user.is_admin,
        auth_method=user.auth_method,
    )


async def _make_token_response(user, db: AsyncSession) -> TokenResponse:
    access = create_access_token(user)
    refresh = await create_refresh_token(user, db)
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        user=_user_response(user),
    )


# ---------------------------------------------------------------------------
# Public endpoints (no auth required)
# ---------------------------------------------------------------------------

@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(db: AsyncSession = Depends(get_db)):
    setup = await is_setup_required(db)
    return AuthStatusResponse(
        setup_required=setup,
        google_enabled=bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET),
    )


@router.post("/setup", response_model=TokenResponse)
async def auth_setup(req: SetupRequest, db: AsyncSession = Depends(get_db)):
    if not await is_setup_required(db):
        raise HTTPException(status_code=409, detail="Setup already completed")

    if req.method == "google":
        if not req.code or not req.redirect_uri:
            raise HTTPException(status_code=400, detail="Google auth requires code and redirect_uri")
        try:
            info = await exchange_google_code(req.code, req.redirect_uri)
        except Exception as e:
            logger.warning("Google code exchange failed during setup: %s", e)
            raise HTTPException(status_code=400, detail=f"Google auth failed: {e}")
        display_name = req.display_name or info["name"]
        user = await get_or_create_google_user(
            db, info["email"], display_name, info.get("picture"), is_admin=True,
        )
    elif req.method == "local":
        if not req.email or not req.password:
            raise HTTPException(status_code=400, detail="Local auth requires email and password")
        display_name = req.display_name or req.email.split("@")[0]
        user = await create_local_user(
            db, req.email, display_name, req.password, is_admin=True,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown auth method: {req.method}")

    return await _make_token_response(user, db)


@router.post("/login", response_model=TokenResponse)
async def auth_login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await get_user_by_email(db, req.email)
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    # Auto-provision API key for existing users (backward compat)
    from app.services.auth import ensure_user_api_key
    await ensure_user_api_key(db, user)
    return await _make_token_response(user, db)


@router.post("/google", response_model=TokenResponse)
async def auth_google(req: GoogleAuthRequest, db: AsyncSession = Depends(get_db)):
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=400, detail="Google OAuth not configured")
    try:
        info = await exchange_google_code(req.code, req.redirect_uri)
    except Exception as e:
        logger.warning("Google code exchange failed: %s", e)
        raise HTTPException(status_code=400, detail=f"Google auth failed: {e}")

    user = await get_or_create_google_user(
        db, info["email"], info["name"], info.get("picture"),
    )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")
    # Auto-provision API key for existing users (backward compat)
    from app.services.auth import ensure_user_api_key
    await ensure_user_api_key(db, user)
    return await _make_token_response(user, db)


@router.post("/refresh", response_model=AccessTokenResponse)
async def auth_refresh(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    token_row = await validate_refresh_token(req.refresh_token, db)
    if not token_row:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    user = await get_user_by_id(db, token_row.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or deactivated")
    access = create_access_token(user)
    return AccessTokenResponse(access_token=access)


@router.post("/logout")
async def auth_logout(req: LogoutRequest, db: AsyncSession = Depends(get_db)):
    await revoke_refresh_token(req.refresh_token, db)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Authenticated endpoints (JWT required)
# ---------------------------------------------------------------------------

@router.get("/integrations")
async def auth_integrations():
    """List active integrations and their identity fields for profile linking."""
    from integrations import discover_identity_fields
    return discover_identity_fields()


@router.get("/me", response_model=UserResponse)
async def auth_me(user=Depends(verify_user)):
    return _user_response(user)


@router.put("/me", response_model=UserResponse)
async def auth_update_me(
    req: UpdateProfileRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(verify_user),
):
    # Re-fetch mutable user within this db session
    user = await get_user_by_id(db, user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if req.display_name is not None:
        user.display_name = req.display_name
    if req.avatar_url is not None:
        user.avatar_url = req.avatar_url
    if req.integration_config is not None:
        user.integration_config = req.integration_config
    await db.commit()
    await db.refresh(user)
    return _user_response(user)


@router.post("/me/change-password")
async def auth_change_password(
    req: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(verify_user),
):
    from app.services.auth import hash_password
    user = await get_user_by_id(db, user.id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.auth_method != "local" or not user.password_hash:
        raise HTTPException(status_code=400, detail="Password change only available for local auth")
    if not verify_password(req.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    user.password_hash = hash_password(req.new_password)
    await db.commit()
    return {"status": "ok"}
