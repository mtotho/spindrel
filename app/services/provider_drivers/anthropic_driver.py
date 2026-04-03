"""Anthropic and Anthropic-compatible provider drivers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.config import settings
from app.services.anthropic_adapter import AnthropicOpenAIAdapter

from .base import ProviderCapabilities, ProviderDriver

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.db.models import ProviderConfig as ProviderConfigRow

# Hardcoded model list — Anthropic doesn't expose a /models endpoint
_ANTHROPIC_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-opus-4-5",
    "claude-sonnet-4-5",
]


class AnthropicDriver(ProviderDriver):
    provider_type = "anthropic"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(chat_completions=True, requires_api_key=True)

    def make_client(self, config: ProviderConfigRow) -> AnthropicOpenAIAdapter:
        return AnthropicOpenAIAdapter(
            api_key=config.api_key or "",
            base_url=config.base_url or "https://api.anthropic.com",
            timeout=settings.LLM_TIMEOUT,
            max_retries=0,
        )

    async def test_connection(
        self, api_key: str | None, base_url: str | None
    ) -> tuple[bool, str]:
        # Direct Anthropic: trust that the key is valid (no cheap probe endpoint)
        return True, "Credentials OK"

    async def list_models(self, config: ProviderConfigRow) -> list[str]:
        return list(_ANTHROPIC_MODELS)


class AnthropicCompatibleDriver(ProviderDriver):
    provider_type = "anthropic-compatible"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            chat_completions=True, list_models=True, requires_base_url=True, requires_api_key=True
        )

    def make_client(self, config: ProviderConfigRow) -> AnthropicOpenAIAdapter:
        return AnthropicOpenAIAdapter(
            api_key=config.api_key or "",
            base_url=config.base_url or "https://api.anthropic.com",
            timeout=settings.LLM_TIMEOUT,
            max_retries=0,
        )

    async def test_connection(
        self, api_key: str | None, base_url: str | None
    ) -> tuple[bool, str]:
        import httpx

        url = (base_url or "https://api.anthropic.com").rstrip("/")
        # Strip /v1 if present (Anthropic endpoints don't use it)
        if url.endswith("/v1"):
            url = url[:-3]
        try:
            async with httpx.AsyncClient(timeout=15.0) as hc:
                resp = await hc.post(
                    f"{url}/v1/messages",
                    headers={
                        "x-api-key": api_key or "",
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={"model": "test", "max_tokens": 1, "messages": []},
                )
                if resp.status_code == 401:
                    return False, "Authentication failed (401)"
                return True, f"Connected (HTTP {resp.status_code})"
        except Exception as exc:
            return False, str(exc)[:200]

    async def list_models(self, config: ProviderConfigRow) -> list[str]:
        import httpx

        url = (config.base_url or "https://api.anthropic.com").rstrip("/")
        if url.endswith("/v1"):
            url = url[:-3]
        try:
            async with httpx.AsyncClient(timeout=15.0) as hc:
                resp = await hc.get(
                    f"{url}/v1/models",
                    headers={
                        "x-api-key": config.api_key or "",
                        "anthropic-version": "2023-06-01",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("data", [])
                    return sorted(m.get("id", "") for m in models if m.get("id"))
        except Exception:
            logger.warning("Failed to list models for anthropic-compatible provider %s", config.id, exc_info=True)
        return []
