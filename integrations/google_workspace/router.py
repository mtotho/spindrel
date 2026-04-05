"""FastAPI router for Google Workspace OAuth flow."""
from __future__ import annotations

import logging
import secrets
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from integrations.google_workspace.config import settings, SCOPE_MAP

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory state tokens with TTL (state -> {created_at, scopes})
_pending_states: dict[str, dict] = {}
_STATE_TTL = 600  # 10 minutes

# Token keys stored as IntegrationSettings
_TOKEN_KEYS = {
    "GWS_REFRESH_TOKEN": True,   # secret
    "GWS_ACCESS_TOKEN": True,    # secret
    "GWS_GRANTED_SCOPES": False,
    "GWS_CONNECTED_EMAIL": False,
}

# Synthetic setup_vars for update_settings (secret flag matching)
_TOKEN_SETUP_VARS = [
    {"key": k, "secret": v} for k, v in _TOKEN_KEYS.items()
]


def _cleanup_expired_states() -> None:
    """Remove expired state tokens."""
    now = time.time()
    expired = [k for k, v in _pending_states.items() if now - v["created_at"] > _STATE_TTL]
    for k in expired:
        del _pending_states[k]


def _get_base_url() -> str:
    """Get the server's base URL for OAuth redirect."""
    try:
        from app.config import settings as app_settings
        return app_settings.BASE_URL.rstrip("/")
    except Exception:
        return "http://localhost:8000"


def _build_scope_string(service_names: list[str]) -> str:
    """Convert service names to Google scope URIs string."""
    scopes = []
    for name in service_names:
        uri = SCOPE_MAP.get(name)
        if uri:
            scopes.append(uri)
    # Always include openid + email for userinfo
    scopes.extend([
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
    ])
    return " ".join(scopes)


@router.get("/auth/start")
async def auth_start(scopes: str = Query(default="drive,gmail,calendar")):
    """Redirect to Google OAuth consent screen."""
    client_id = settings.GWS_CLIENT_ID
    if not client_id:
        raise HTTPException(status_code=400, detail="GWS_CLIENT_ID not configured")

    _cleanup_expired_states()

    service_names = [s.strip() for s in scopes.split(",") if s.strip()]
    state = secrets.token_urlsafe(32)
    _pending_states[state] = {
        "created_at": time.time(),
        "scopes": service_names,
    }

    base_url = _get_base_url()
    redirect_uri = f"{base_url}/integrations/google_workspace/auth/callback"
    scope_string = _build_scope_string(service_names)

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope_string,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    url = httpx.URL("https://accounts.google.com/o/oauth2/v2/auth", params=params)
    return RedirectResponse(str(url))


@router.get("/auth/callback")
async def auth_callback(
    code: str = Query(None),
    state: str = Query(...),
    error: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Handle OAuth callback — exchange code for tokens."""
    _cleanup_expired_states()

    # Handle user-denied consent or other OAuth errors
    if error:
        base_url = _get_base_url()
        logger.warning("OAuth callback error: %s", error)
        return RedirectResponse(f"{base_url}/admin/integrations/google_workspace?error={error}")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    state_data = _pending_states.pop(state, None)
    if not state_data:
        raise HTTPException(status_code=400, detail="Invalid or expired state token")

    client_id = settings.GWS_CLIENT_ID
    client_secret = settings.GWS_CLIENT_SECRET
    base_url = _get_base_url()
    redirect_uri = f"{base_url}/integrations/google_workspace/auth/callback"

    # Exchange code for tokens
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    if resp.status_code != 200:
        logger.error("Token exchange failed: %s %s", resp.status_code, resp.text[:500])
        raise HTTPException(status_code=502, detail="Failed to exchange authorization code")

    token_data = resp.json()
    refresh_token = token_data.get("refresh_token", "")
    access_token = token_data.get("access_token", "")
    granted_scopes = token_data.get("scope", "")

    if not refresh_token:
        logger.warning("No refresh_token in OAuth response — user may need to re-consent")

    # Get user email from userinfo
    email = ""
    if access_token:
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                info_resp = await http.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if info_resp.status_code == 200:
                    email = info_resp.json().get("email", "")
        except Exception:
            logger.debug("Failed to fetch userinfo email", exc_info=True)

    # Map granted scope URIs back to service names for display
    scope_uri_to_name = {v: k for k, v in SCOPE_MAP.items()}
    granted_service_names = []
    for uri in granted_scopes.split():
        name = scope_uri_to_name.get(uri)
        if name:
            granted_service_names.append(name)

    # Store tokens as integration settings
    from app.services.integration_settings import update_settings

    updates = {
        "GWS_ACCESS_TOKEN": access_token,
        "GWS_GRANTED_SCOPES": ",".join(granted_service_names) if granted_service_names else granted_scopes,
        "GWS_CONNECTED_EMAIL": email,
    }
    if refresh_token:
        updates["GWS_REFRESH_TOKEN"] = refresh_token

    await update_settings("google_workspace", updates, _TOKEN_SETUP_VARS, db)

    logger.info("Google Workspace OAuth connected for %s (scopes: %s)", email, granted_service_names)

    # Redirect back to admin integration page
    return RedirectResponse(f"{base_url}/admin/integrations/google_workspace")


@router.get("/auth/status")
async def auth_status():
    """Check if a Google account is connected."""
    from app.services.integration_settings import get_value

    refresh_token = get_value("google_workspace", "GWS_REFRESH_TOKEN")
    connected = bool(refresh_token)
    scopes_str = get_value("google_workspace", "GWS_GRANTED_SCOPES") if connected else ""
    email = get_value("google_workspace", "GWS_CONNECTED_EMAIL") if connected else ""

    scopes = [s.strip() for s in scopes_str.split(",") if s.strip()] if scopes_str else []

    return {
        "connected": connected,
        "scopes": scopes,
        "email": email or None,
    }


@router.post("/auth/disconnect")
async def auth_disconnect(db: AsyncSession = Depends(get_db)):
    """Disconnect Google account — revoke and delete stored tokens."""
    from app.services.integration_settings import get_value, delete_setting

    # Try to revoke the token with Google
    access_token = get_value("google_workspace", "GWS_ACCESS_TOKEN")
    if access_token:
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                await http.post(
                    "https://oauth2.googleapis.com/revoke",
                    params={"token": access_token},
                )
        except Exception:
            logger.debug("Token revocation failed (non-fatal)", exc_info=True)

    # Delete all stored token settings
    for key in _TOKEN_KEYS:
        try:
            await delete_setting("google_workspace", key, db)
        except Exception:
            pass

    logger.info("Google Workspace OAuth disconnected")
    return {"disconnected": True}
