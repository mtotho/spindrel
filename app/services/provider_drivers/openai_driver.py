"""OpenAI and OpenAI-compatible provider drivers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from app.config import settings

from .base import ProviderCapabilities, ProviderDriver

if TYPE_CHECKING:
    from app.db.models import ProviderConfig as ProviderConfigRow


class OpenAIDriver(ProviderDriver):
    provider_type = "openai"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(list_models=True)

    def make_client(self, config: ProviderConfigRow) -> AsyncOpenAI:
        kw: dict = {
            "api_key": config.api_key,
            "timeout": settings.LLM_TIMEOUT,
            "max_retries": 0,
        }
        if config.base_url:
            kw["base_url"] = config.base_url
        return AsyncOpenAI(**kw)

    async def test_connection(
        self, api_key: str | None, base_url: str | None
    ) -> tuple[bool, str]:
        try:
            kw: dict = {
                "api_key": api_key or "dummy",
                "timeout": 15.0,
                "max_retries": 0,
            }
            if base_url:
                kw["base_url"] = base_url
            client = AsyncOpenAI(**kw)
            models = await client.models.list()
            return True, f"Connected ({len(models.data)} models)"
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


class OpenAICompatibleDriver(OpenAIDriver):
    provider_type = "openai-compatible"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(list_models=True, requires_base_url=True)
