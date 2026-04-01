"""Anthropic and Anthropic-compatible provider drivers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from app.config import settings

from .base import ProviderCapabilities, ProviderDriver

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
        return ProviderCapabilities(requires_api_key=True)

    def make_client(self, config: ProviderConfigRow) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=config.base_url or "https://api.anthropic.com/v1",
            api_key=config.api_key,
            timeout=settings.LLM_TIMEOUT,
            max_retries=0,
            default_headers={"anthropic-version": "2023-06-01"},
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
            list_models=True, requires_base_url=True, requires_api_key=True
        )

    def make_client(self, config: ProviderConfigRow) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=config.base_url or "https://api.anthropic.com/v1",
            api_key=config.api_key,
            timeout=settings.LLM_TIMEOUT,
            max_retries=0,
            default_headers={"anthropic-version": "2023-06-01"},
        )

    async def test_connection(
        self, api_key: str | None, base_url: str | None
    ) -> tuple[bool, str]:
        import httpx

        url = (base_url or "https://api.anthropic.com/v1").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=15.0) as hc:
                resp = await hc.post(
                    f"{url}/messages",
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
        from app.services.providers import get_llm_client

        try:
            client = get_llm_client(config.id)
            models = await client.models.list()
            return sorted(m.id for m in models.data)
        except Exception:
            return []
