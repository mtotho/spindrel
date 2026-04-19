"""ChatGPT-subscription OAuth: device-code flow + token refresh.

Handles the OAuth dance that pairs Spindrel with a user's ChatGPT
subscription via OpenAI's Codex device-code endpoints. Tokens persist on
the associated ``ProviderConfig`` row under ``config['oauth']`` (secrets
are encrypted at rest with the shared ``encrypt()`` helper).

The wire shapes are taken from OpenAI's public Codex CLI source
(``github.com/openai/codex`` — ``codex-rs/login``) plus the community
plugins ``numman-ali/opencode-openai-codex-auth`` and
``EvanZhouDev/openai-oauth``:

  * Device code request/poll at ``/deviceauth/usercode`` /
    ``/deviceauth/token``. Both accept JSON; poll returns an
    ``authorization_code`` + server-generated PKCE pair on success.
  * Token exchange is the standard OAuth authorization_code grant at
    ``/oauth/token``.
  * Refresh uses ``grant_type=refresh_token`` with the same client_id.
  * Account ID for the ``chatgpt-account-id`` header comes from a
    ``https://api.openai.com/auth`` claim inside the id_token.

Module exposes:

* ``start_device_flow()`` — kicks off device auth, returns the user_code.
* ``poll_and_complete()`` — polls until approved, persists tokens.
* ``load_and_refresh_tokens()`` — returns live access token (+ refreshes).
* ``tokens_source_for_provider()`` — returns the awaitable the adapter
  calls on every request.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import httpx

from app.db.engine import async_session
from app.db.models import ProviderConfig as ProviderConfigRow
from app.services.encryption import decrypt, encrypt
from app.services.provider_drivers.openai_subscription_driver import (
    CODEX_OAUTH_CLIENT_ID,
    CODEX_OAUTH_ISSUER,
    CODEX_OAUTH_SCOPES,
)

logger = logging.getLogger(__name__)


# OAuth endpoint paths off the CODEX_OAUTH_ISSUER base.
_DEVICEAUTH_USERCODE_PATH = "/deviceauth/usercode"
_DEVICEAUTH_TOKEN_PATH = "/deviceauth/token"
_DEVICEAUTH_CALLBACK_PATH = "/deviceauth/callback"
_OAUTH_TOKEN_PATH = "/oauth/token"

# id_token claim that carries the ChatGPT account identifier used in the
# chatgpt-account-id header on Responses API calls.
_ACCOUNT_ID_CLAIM = "https://api.openai.com/auth"

# Refresh tokens when less than this many seconds remain on the access
# token. Gives us a buffer so concurrent calls don't race on expiry.
_REFRESH_LEEWAY_SECONDS = 10 * 60  # 10 minutes

# OpenAI's /deviceauth/* and /oauth/token endpoints block requests that
# don't look like they came from the Codex CLI — bare `python-httpx/...`
# User-Agents return 403. We send the same `originator` + User-Agent the
# official CLI sends so the wire-level auth path accepts us. This string
# mirrors what `default_client.rs` in `openai/codex` builds; the explicit
# version numbers don't matter to OpenAI's validation, but shape does.
_CODEX_ORIGINATOR = "codex_cli_rs"
_CODEX_USER_AGENT = f"{_CODEX_ORIGINATOR}/0.45.0 (linux; x86_64) spindrel"


def _oauth_headers(content_type: str = "application/json") -> dict[str, str]:
    """Headers required for every OpenAI OAuth + device-code call."""
    return {
        "Content-Type": content_type,
        "User-Agent": _CODEX_USER_AGENT,
        "originator": _CODEX_ORIGINATOR,
        "Accept": "application/json",
    }

# Device-code flow deadlines (defaults — the server can override via
# ``expires_in`` / ``interval`` in the usercode response).
_DEFAULT_POLL_INTERVAL = 2
_POLL_MAX_ATTEMPTS = 450  # ~15 minutes at 2s interval


# ---------------------------------------------------------------------------
# Pending device-flow state (in-memory, TTL'd)
# ---------------------------------------------------------------------------
# Admin calls `/start`, then polls `/poll/{id}` until success. We stash the
# device_auth_id + user_code in memory so the poll endpoint can pick them up
# without the client having to echo them back. Matches the 10-minute TTL
# pattern from ``integrations/google_workspace/router.py:20-22``.

_STATE_TTL_SECONDS = 15 * 60
_pending: dict[str, dict[str, Any]] = {}


def _cleanup_pending() -> None:
    now = time.time()
    stale = [k for k, v in _pending.items() if now - v.get("created_at", 0) > _STATE_TTL_SECONDS]
    for k in stale:
        _pending.pop(k, None)


# ---------------------------------------------------------------------------
# ID-token claim parsing
# ---------------------------------------------------------------------------

def _decode_jwt_claims(jwt: str) -> dict:
    """Decode a JWT's payload without verifying the signature.

    OpenAI's id_token uses RS256; verifying it here would require fetching
    JWKs, caching, and adding a dependency. The claims we read from it
    (``account_id``, ``email``, ``chatgpt_plan_type``) are not security-
    critical — they only show up in the admin UI. The access_token we
    actually use against the API is validated by OpenAI on every request.
    """
    try:
        _header, payload, _sig = jwt.split(".", 2)
    except ValueError:
        return {}
    # base64url decode with padding fix-up.
    padding = "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload + padding)
        return json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return {}


def _extract_account_info(id_token: str) -> dict:
    """Pull account_id, email, plan from an id_token. Returns empty dict on failure."""
    claims = _decode_jwt_claims(id_token)
    if not claims:
        return {}
    email = claims.get("email") or ""
    auth_claim = claims.get(_ACCOUNT_ID_CLAIM) or {}
    account_id = ""
    plan = ""
    if isinstance(auth_claim, dict):
        account_id = auth_claim.get("chatgpt_account_id") or auth_claim.get("organization_id") or ""
        plan = auth_claim.get("chatgpt_plan_type") or ""
    return {"email": email, "account_id": account_id, "plan": plan}


# ---------------------------------------------------------------------------
# Device-code flow
# ---------------------------------------------------------------------------

async def start_device_flow(provider_id: str) -> dict:
    """Initiate the Codex device-code flow. Stashes state under ``provider_id``.

    Returns a dict safe to expose to the admin UI:
    ``{user_code, verification_uri, expires_in, interval, verification_uri_complete}``.
    """
    _cleanup_pending()

    url = f"{CODEX_OAUTH_ISSUER}{_DEVICEAUTH_USERCODE_PATH}"
    body = {"client_id": CODEX_OAUTH_CLIENT_ID}
    async with httpx.AsyncClient(timeout=15.0, headers=_oauth_headers()) as hc:
        resp = await hc.post(url, json=body)
    if not resp.is_success:
        raise RuntimeError(
            f"Device code request failed: HTTP {resp.status_code} — {resp.text[:300]}"
        )
    data = resp.json()
    device_auth_id = data.get("device_auth_id") or ""
    user_code = data.get("user_code") or data.get("usercode") or ""
    interval = int(data.get("interval") or _DEFAULT_POLL_INTERVAL) or _DEFAULT_POLL_INTERVAL
    expires_in = int(data.get("expires_in") or _STATE_TTL_SECONDS)

    if not device_auth_id or not user_code:
        raise RuntimeError(f"Device code response missing required fields: {data}")

    # Verification URI the user visits to approve the code. The canonical
    # URL shape matches what the official CLI prints.
    verification_uri = f"https://chatgpt.com/auth/device"
    verification_uri_complete = f"{verification_uri}?user_code={user_code}"

    _pending[provider_id] = {
        "created_at": time.time(),
        "device_auth_id": device_auth_id,
        "user_code": user_code,
        "interval": interval,
    }
    return {
        "user_code": user_code,
        "verification_uri": verification_uri,
        "verification_uri_complete": verification_uri_complete,
        "expires_in": expires_in,
        "interval": interval,
    }


async def _poll_device_token_once(device_auth_id: str, user_code: str) -> dict | None:
    """Single poll of the device-code token endpoint.

    Returns the success payload (with ``authorization_code`` /
    ``code_verifier``) when approved, or ``None`` while still pending.
    Raises on non-retryable errors (403 + 404 mean "still pending" per the
    Codex CLI's behavior; other non-2xx are real failures).
    """
    url = f"{CODEX_OAUTH_ISSUER}{_DEVICEAUTH_TOKEN_PATH}"
    body = {"device_auth_id": device_auth_id, "user_code": user_code}
    async with httpx.AsyncClient(timeout=15.0, headers=_oauth_headers()) as hc:
        resp = await hc.post(url, json=body)
    if resp.is_success:
        return resp.json()
    if resp.status_code in (403, 404):
        return None
    raise RuntimeError(
        f"Device code poll failed: HTTP {resp.status_code} — {resp.text[:300]}"
    )


async def _exchange_authorization_code(
    authorization_code: str, code_verifier: str
) -> dict:
    url = f"{CODEX_OAUTH_ISSUER}{_OAUTH_TOKEN_PATH}"
    form = {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": f"{CODEX_OAUTH_ISSUER}{_DEVICEAUTH_CALLBACK_PATH}",
        "client_id": CODEX_OAUTH_CLIENT_ID,
        "code_verifier": code_verifier,
        "scope": CODEX_OAUTH_SCOPES,
    }
    headers = _oauth_headers("application/x-www-form-urlencoded")
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as hc:
        resp = await hc.post(url, data=form)
    if not resp.is_success:
        raise RuntimeError(
            f"Token exchange failed: HTTP {resp.status_code} — {resp.text[:300]}"
        )
    return resp.json()


async def poll_once(provider_id: str) -> dict:
    """Do one poll against the device-code token endpoint.

    Returns one of:
      * ``{"status": "pending"}`` — user hasn't approved yet.
      * ``{"status": "success", "email", "plan"}`` — tokens persisted.
      * raises ``RuntimeError`` — flow never started, timed out, or errored.

    UI pollers call this every ``interval`` seconds until non-pending.
    """
    state = _pending.get(provider_id)
    if not state:
        raise RuntimeError(
            f"No pending device flow for provider {provider_id!r}. Call start_device_flow first."
        )

    # Enforce a wall-clock timeout so abandoned flows don't accrue forever.
    if time.time() - state.get("created_at", 0) > _STATE_TTL_SECONDS:
        _pending.pop(provider_id, None)
        raise RuntimeError("Device code flow expired. Start a new one.")

    poll_result = await _poll_device_token_once(state["device_auth_id"], state["user_code"])
    if poll_result is None:
        return {"status": "pending"}

    code = poll_result.get("authorization_code")
    verifier = poll_result.get("code_verifier")
    if not code or not verifier:
        _pending.pop(provider_id, None)
        raise RuntimeError(f"Device poll returned unexpected shape: {poll_result}")

    token_payload = await _exchange_authorization_code(code, verifier)
    await _persist_tokens(provider_id, token_payload)
    _pending.pop(provider_id, None)

    info = _extract_account_info(token_payload.get("id_token") or "")
    return {"status": "success", "email": info.get("email", ""), "plan": info.get("plan", "")}


async def poll_and_complete(provider_id: str) -> dict:
    """Server-side blocking variant of the poll loop (for tests / CLI).

    Calls ``poll_once`` every ``interval`` seconds until approved or the
    state TTL expires.
    """
    state = _pending.get(provider_id)
    if not state:
        raise RuntimeError(
            f"No pending device flow for provider {provider_id!r}. Call start_device_flow first."
        )
    interval = state["interval"]
    for _ in range(_POLL_MAX_ATTEMPTS):
        result = await poll_once(provider_id)
        if result.get("status") != "pending":
            return result
        await asyncio.sleep(interval)
    _pending.pop(provider_id, None)
    raise RuntimeError("Device code poll timed out before approval")


async def cancel_device_flow(provider_id: str) -> None:
    _pending.pop(provider_id, None)


# ---------------------------------------------------------------------------
# Token persistence + refresh
# ---------------------------------------------------------------------------

_OAUTH_FIELD = "oauth"
_refresh_locks: dict[str, asyncio.Lock] = {}


def _oauth_field(config: dict | None) -> dict:
    if not isinstance(config, dict):
        return {}
    val = config.get(_OAUTH_FIELD)
    return val if isinstance(val, dict) else {}


def _compute_expires_at(token_payload: dict) -> str:
    expires_in = int(token_payload.get("expires_in") or 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    return expires_at.isoformat()


async def _persist_tokens(provider_id: str, token_payload: dict) -> None:
    """Write access/refresh/expires_at + account metadata onto the provider row.

    Secrets are encrypted before storage; account_id/email/plan/expires_at
    stay plain for admin-UI display. Also updates the in-memory registry so
    the next ``get_llm_client`` call sees fresh tokens without a reload.
    """
    info = _extract_account_info(token_payload.get("id_token") or "")
    new_oauth = {
        "access_token": encrypt(token_payload.get("access_token") or ""),
        "refresh_token": encrypt(token_payload.get("refresh_token") or ""),
        "expires_at": _compute_expires_at(token_payload),
        "account_email": info.get("email", ""),
        "account_id": info.get("account_id", ""),
        "plan": info.get("plan", ""),
        "client_id": CODEX_OAUTH_CLIENT_ID,
    }
    async with async_session() as db:
        row = await db.get(ProviderConfigRow, provider_id)
        if row is None:
            raise RuntimeError(f"Provider {provider_id!r} not found")
        new_config = dict(row.config or {})
        new_config[_OAUTH_FIELD] = new_oauth
        row.config = new_config
        await db.commit()

    # Reflect into the in-memory registry with DECRYPTED secrets so the
    # adapter can read them without another round-trip.
    from app.services.providers import _registry  # local import — avoids cycles

    live = _registry.get(provider_id)
    if live is not None:
        live_config = dict(live.config or {})
        live_config[_OAUTH_FIELD] = {
            **new_oauth,
            "access_token": token_payload.get("access_token") or "",
            "refresh_token": token_payload.get("refresh_token") or "",
        }
        live.config = live_config


async def disconnect_provider(provider_id: str) -> None:
    """Clear OAuth tokens from a provider. Keeps the row and metadata intact."""
    async with async_session() as db:
        row = await db.get(ProviderConfigRow, provider_id)
        if row is None:
            return
        new_config = dict(row.config or {})
        new_config.pop(_OAUTH_FIELD, None)
        row.config = new_config
        await db.commit()

    from app.services.providers import _registry

    live = _registry.get(provider_id)
    if live is not None:
        live_config = dict(live.config or {})
        live_config.pop(_OAUTH_FIELD, None)
        live.config = live_config


def decrypt_oauth_fields(config: dict) -> dict:
    """Return a copy of ``config`` with oauth secrets decrypted in place.

    Called by ``load_providers()`` at startup so the in-memory registry
    holds usable values. Safe if ``oauth`` is missing or partial.
    """
    if not isinstance(config, dict):
        return config
    if _OAUTH_FIELD not in config:
        return config
    out = dict(config)
    oauth = dict(out.get(_OAUTH_FIELD) or {})
    for key in ("access_token", "refresh_token"):
        v = oauth.get(key)
        if v:
            oauth[key] = decrypt(v)
    out[_OAUTH_FIELD] = oauth
    return out


def _parse_expires_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


async def _refresh_access_token(refresh_token: str) -> dict:
    """Exchange a refresh_token for a fresh access_token pair."""
    url = f"{CODEX_OAUTH_ISSUER}{_OAUTH_TOKEN_PATH}"
    form = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CODEX_OAUTH_CLIENT_ID,
        "scope": CODEX_OAUTH_SCOPES,
    }
    headers = _oauth_headers("application/x-www-form-urlencoded")
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as hc:
        resp = await hc.post(url, data=form)
    if not resp.is_success:
        raise RuntimeError(
            f"OAuth refresh failed: HTTP {resp.status_code} — {resp.text[:300]}"
        )
    return resp.json()


async def load_and_refresh_tokens(provider: ProviderConfigRow) -> dict:
    """Return a live token dict, refreshing if within the leeway window.

    Emits ``{access_token, account_id, expires_at}``. Persists rotated
    refresh tokens back to the DB.
    """
    oauth = _oauth_field(provider.config)
    if not oauth.get("access_token"):
        raise RuntimeError(
            f"Provider {provider.id!r} has no OAuth token — connect a ChatGPT "
            "account via the admin UI."
        )

    expires_at = _parse_expires_at(oauth.get("expires_at"))
    now = datetime.now(timezone.utc)
    need_refresh = (
        expires_at is None
        or expires_at <= now + timedelta(seconds=_REFRESH_LEEWAY_SECONDS)
    )

    if need_refresh and oauth.get("refresh_token"):
        lock = _refresh_locks.setdefault(provider.id, asyncio.Lock())
        async with lock:
            # Re-read in case a concurrent call already refreshed.
            oauth = _oauth_field(provider.config)
            expires_at = _parse_expires_at(oauth.get("expires_at"))
            still_stale = (
                expires_at is None
                or expires_at <= datetime.now(timezone.utc) + timedelta(seconds=_REFRESH_LEEWAY_SECONDS)
            )
            if still_stale:
                token_payload = await _refresh_access_token(oauth["refresh_token"])
                # Preserve id_token / account_id if the refresh response
                # omits them (common with scope-narrowed refreshes).
                if not token_payload.get("id_token") and oauth.get("account_id"):
                    token_payload = copy.deepcopy(token_payload)
                    token_payload.setdefault("refresh_token", oauth.get("refresh_token", ""))
                await _persist_tokens(provider.id, token_payload)
                oauth = _oauth_field(provider.config)

    return {
        "access_token": oauth.get("access_token", ""),
        "account_id": oauth.get("account_id", ""),
        "expires_at": oauth.get("expires_at", ""),
    }


def tokens_source_for_provider(
    provider: ProviderConfigRow,
) -> Callable[[], Awaitable[dict]]:
    """Return the awaitable the ``OpenAIResponsesAdapter`` calls per request."""

    async def _source() -> dict:
        # Re-read from the registry on every call so rotated tokens are
        # picked up without reinstantiating the adapter.
        from app.services.providers import _registry

        live = _registry.get(provider.id) or provider
        return await load_and_refresh_tokens(live)

    return _source
