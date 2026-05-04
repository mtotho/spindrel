"""OpenAI-subscription provider driver.

Authenticates against OpenAI's Codex Responses API using a ChatGPT OAuth
Bearer token instead of a regular API key. The token is obtained via the
device-code flow implemented in ``app/services/openai_oauth.py`` and
persisted (encrypted) into ``ProviderConfig.config['oauth']``.

Uses ``OpenAIResponsesAdapter`` as the OpenAI-compatible client facade so
the rest of the agent loop can treat this provider identically to an
API-key OpenAI provider. There is no proven model-catalog endpoint for this
OAuth path; model rows are seeded from a conservative fallback list and can
be edited in the admin UI.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from app.config import settings
from app.services.openai_responses_adapter import (
    DEFAULT_CODEX_BASE_URL,
    OpenAIResponsesAdapter,
)

from .base import ProviderCapabilities, ProviderDriver

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

# Seed model list for the ChatGPT subscription OAuth path. The Codex
# Responses base is proven for ``POST /responses`` only; do not probe
# ``GET /models`` here unless we have a sourced, tested catalog endpoint.
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
        """Return the seeded subscription model catalog.

        The ChatGPT OAuth token is for the Codex Responses endpoint. We have
        not verified a supported ``/models`` endpoint for that backend, so
        listing is deliberately local: DB rows are seeded from this fallback
        list and admins can add/edit models manually.
        """
        return list(OAUTH_MODELS_FALLBACK)
