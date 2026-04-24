"""OpenAI-subscription provider driver.

Authenticates against OpenAI's Codex Responses API using a ChatGPT OAuth
Bearer token instead of a regular API key. The token is obtained via the
device-code flow implemented in ``app/services/openai_oauth.py`` and
persisted (encrypted) into ``ProviderConfig.config['oauth']``.

Uses ``OpenAIResponsesAdapter`` as the OpenAI-compatible client facade so
the rest of the agent loop can treat this provider identically to an
API-key OpenAI provider. Models exposed here are the ones the ChatGPT
subscription OAuth flow actually serves — they are a subset of the public
OpenAI catalog.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from app.config import settings
from app.services.openai_responses_adapter import (
    DEFAULT_CODEX_BASE_URL,
    OpenAIResponsesAdapter,
)

from .base import ProviderCapabilities, ProviderDriver

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.db.models import ProviderConfig as ProviderConfigRow


# OAuth client_id used by the official OpenAI Codex CLI (public, visible in
# its authorize URLs). The community OAuth plugins reuse this value for
# personal self-hosted installs. Kept as a module constant so it's easy to
# audit and swap if OpenAI rotates it.
#
# Provenance: github.com/openai/codex — codex-rs/login passes this to the
# PKCE + device-code flows. Also documented by numman-ali/opencode-openai-
# codex-auth and EvanZhouDev/openai-oauth.
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_ISSUER = "https://auth.openai.com"
CODEX_OAUTH_SCOPES = (
    "openid profile email offline_access "
    "api.connectors.read api.connectors.invoke"
)

# Short TTL cache for the live model list. list_models() is called from
# the admin UI (Refresh button, type dropdown), not the hot request path,
# so we keep this small — long enough to absorb rapid re-clicks, short
# enough that a model OpenAI adds today is visible within the hour.
_LIVE_MODELS_TTL_SECONDS = 15 * 60
_live_models_cache: dict[str, tuple[float, list[str]]] = {}


async def _fetch_live_models(config: "ProviderConfigRow") -> list[str]:
    """Return the account's Codex model catalog, or [] if unreachable.

    Hits ``GET {base}/models`` with the provider's OAuth bearer. Any
    failure (no tokens, network error, non-2xx, malformed response)
    returns [] so callers can fall back cleanly.
    """
    import time

    # Local imports to avoid a cycle (openai_oauth imports this module).
    from app.services.openai_oauth import load_and_refresh_tokens
    from app.services.openai_responses_adapter import DEFAULT_CODEX_BASE_URL

    cache_key = config.id
    hit = _live_models_cache.get(cache_key)
    now = time.monotonic()
    if hit and now - hit[0] < _LIVE_MODELS_TTL_SECONDS:
        return list(hit[1])

    try:
        tokens = await load_and_refresh_tokens(config)
    except Exception as exc:
        logger.debug("Codex /models skipped — no OAuth tokens for %s: %s", config.id, exc)
        return []

    access_token = tokens.get("access_token") or ""
    if not access_token:
        return []

    base_url = (config.base_url or DEFAULT_CODEX_BASE_URL).rstrip("/")
    url = f"{base_url}/models"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": f"codex_cli_rs/0.45.0 (linux; x86_64) spindrel",
        "originator": "codex_cli_rs",
        "OpenAI-Beta": "responses=experimental",
    }
    account_id = tokens.get("account_id") or ""
    if account_id:
        headers["chatgpt-account-id"] = account_id

    try:
        async with httpx.AsyncClient(timeout=10.0) as hc:
            resp = await hc.get(url, headers=headers)
        if not resp.is_success:
            logger.info("Codex /models returned HTTP %s for %s", resp.status_code, config.id)
            return []
        data = resp.json()
    except Exception as exc:
        logger.info("Codex /models fetch failed for %s: %s", config.id, exc)
        return []

    # Response shape mirrors OpenAI: {"object":"list","data":[{"id": "..."}]}
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    ids = [it.get("id") for it in items if isinstance(it, dict) and it.get("id")]
    ids = [mid for mid in ids if isinstance(mid, str)]
    if ids:
        _live_models_cache[cache_key] = (now, ids)
    return ids


# Fallback model list used when the live ``/models`` query can't run
# (provider not yet OAuth-connected, transient network failure, etc.).
# The Codex Responses base exposes a ``/models`` endpoint that returns
# the authoritative catalog for a given account — we prefer that, and
# only fall back to this list so the admin dropdown isn't empty before
# a user completes the OAuth dance.
OAUTH_MODELS_FALLBACK: tuple[str, ...] = (
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.2",
)

# Legacy alias retained so other modules (``providers.py`` seed path)
# keep working without a churn commit. Treat as "fallback", not truth.
OAUTH_MODELS = OAUTH_MODELS_FALLBACK


class OpenAISubscriptionDriver(ProviderDriver):
    provider_type = "openai-subscription"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            chat_completions=True,
            list_models=True,
            requires_api_key=False,
            requires_base_url=False,
        )

    def make_client(self, config: "ProviderConfigRow") -> OpenAIResponsesAdapter:
        from app.services.openai_oauth import tokens_source_for_provider

        headers = self._extra_headers(config) or None
        return OpenAIResponsesAdapter(
            tokens_source=tokens_source_for_provider(config),
            base_url=config.base_url or DEFAULT_CODEX_BASE_URL,
            timeout=settings.LLM_TIMEOUT,
            default_headers=headers,
        )

    async def test_connection(
        self, api_key: str | None, base_url: str | None
    ) -> tuple[bool, str]:
        # For subscription providers the creds live in ``config['oauth']``
        # rather than ``api_key``. The admin UI has a separate "Connect
        # ChatGPT Account" flow (see ``openai_oauth`` router) that also
        # validates reachability; this handler is just the probe the
        # standard "Test Connection" button hits. We confirm the auth
        # issuer is reachable, which fails closed if the user is offline.
        issuer = CODEX_OAUTH_ISSUER
        try:
            async with httpx.AsyncClient(timeout=10.0) as hc:
                resp = await hc.get(f"{issuer}/.well-known/openid-configuration")
                if resp.status_code == 200:
                    return True, "Codex OAuth issuer reachable — connect via admin UI"
                return False, f"Issuer returned HTTP {resp.status_code}"
        except Exception as exc:
            return False, f"Cannot reach {issuer}: {str(exc)[:200]}"

    async def list_models(self, config: "ProviderConfigRow") -> list[str]:
        """Query the Codex ``/models`` endpoint for the account's catalog.

        OpenAI rotates what's exposed over the OAuth path (naming shifts
        across GPT-5 point releases, preview gates open and close per
        account). Hitting the endpoint directly keeps us honest. Returns
        the fallback list if the provider isn't OAuth-connected yet, or
        if the fetch fails for any reason — callers layer a DB fallback
        on top of that in ``list_models_for_provider``.
        """
        live = await _fetch_live_models(config)
        if live:
            return live
        return list(OAUTH_MODELS_FALLBACK)
