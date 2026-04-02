"""Base driver class and capabilities dataclass for provider drivers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:
    from openai import AsyncOpenAI

    from app.db.models import ProviderConfig as ProviderConfigRow


@dataclass
class ProviderCapabilities:
    """Declares what a provider type can do beyond basic chat completions."""

    list_models: bool = False
    pull_model: bool = False
    delete_model: bool = False
    model_info: bool = False
    running_models: bool = False
    pricing: bool = False
    requires_base_url: bool = False
    requires_api_key: bool = True
    management_key: bool = False


class ProviderDriver:
    """Base class for provider-type-specific logic.

    Drivers are stateless singletons — all persistent state (caches, registries)
    stays in providers.py.  Drivers handle:
      - Client construction
      - Connection testing
      - Model listing (plain + enriched)
      - Provider-specific operations (pull, delete, info, etc.)
    """

    provider_type: str = ""

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    def make_client(self, config: ProviderConfigRow) -> AsyncOpenAI:
        raise NotImplementedError

    async def test_connection(
        self, api_key: str | None, base_url: str | None
    ) -> tuple[bool, str]:
        """Test connectivity. Returns (ok, message)."""
        raise NotImplementedError

    async def list_models(self, config: ProviderConfigRow) -> list[str]:
        """Return plain model ID list."""
        return []

    async def list_models_enriched(
        self, config: ProviderConfigRow
    ) -> list[dict]:
        """Return enriched model dicts with id, display, and optional metadata.

        Default implementation wraps list_models().
        """
        ids = await self.list_models(config)
        return [{"id": mid, "display": mid} for mid in ids]

    async def pull_model(
        self, config: ProviderConfigRow, model_name: str
    ) -> AsyncIterator[dict]:
        raise NotImplementedError

    async def delete_model(
        self, config: ProviderConfigRow, model_name: str
    ) -> bool:
        raise NotImplementedError

    async def get_model_info(
        self, config: ProviderConfigRow, model_name: str
    ) -> dict:
        raise NotImplementedError

    async def get_running_models(self, config: ProviderConfigRow) -> list[dict]:
        raise NotImplementedError

    async def fetch_pricing(
        self, config: ProviderConfigRow
    ) -> dict[str, dict]:
        raise NotImplementedError
