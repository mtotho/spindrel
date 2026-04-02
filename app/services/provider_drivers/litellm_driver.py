"""LiteLLM provider driver with pricing/model-info fetch."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from openai import AsyncOpenAI

from app.config import settings

from .base import ProviderCapabilities, ProviderDriver

if TYPE_CHECKING:
    from app.db.models import ProviderConfig as ProviderConfigRow

logger = logging.getLogger(__name__)


def _litellm_mgmt_key(config: ProviderConfigRow | None) -> str:
    """Return the management key for a LiteLLM provider (or .env fallback key)."""
    if config is not None:
        mgmt = (config.config or {}).get("management_key")
        if mgmt:
            return mgmt
        return config.api_key or settings.LITELLM_API_KEY or "dummy"
    return settings.LITELLM_API_KEY or "dummy"


class LiteLLMDriver(ProviderDriver):
    provider_type = "litellm"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            list_models=True,
            pricing=True,
            requires_base_url=True,
            requires_api_key=True,
            management_key=True,
        )

    def make_client(self, config: ProviderConfigRow) -> AsyncOpenAI:
        return AsyncOpenAI(
            base_url=config.base_url or settings.LITELLM_BASE_URL,
            api_key=config.api_key or settings.LITELLM_API_KEY or "dummy",
            timeout=settings.LLM_TIMEOUT,
            max_retries=0,
        )

    async def test_connection(
        self, api_key: str | None, base_url: str | None
    ) -> tuple[bool, str]:
        try:
            kw: dict = {
                "api_key": api_key or "dummy",
                "timeout": 15.0,
                "max_retries": 0,
                "base_url": base_url or settings.LITELLM_BASE_URL,
            }
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

    async def fetch_pricing(
        self, config: ProviderConfigRow
    ) -> dict[str, dict]:
        """Fetch /model/info from a LiteLLM proxy.

        Returns {model_name: {max_tokens, input_cost_per_1m, output_cost_per_1m, ...}}.
        """
        import httpx

        base = config.base_url or settings.LITELLM_BASE_URL
        if not base:
            return {}
        key = _litellm_mgmt_key(config)
        return await _fetch_litellm_model_info(base, key)


def _fmt_cost(per_token: float | None) -> str | None:
    """Format per-token cost as a human-readable per-1M string, e.g. '$3.00'."""
    if per_token is None:
        return None
    per_1m = per_token * 1_000_000
    if per_1m >= 1:
        return f"${per_1m:.2f}"
    elif per_1m >= 0.01:
        return f"${per_1m:.3f}"
    else:
        return f"${per_1m:.4f}"


async def _fetch_litellm_model_info(
    base_url: str, api_key: str
) -> dict[str, dict]:
    """Fetch /model/info from a LiteLLM proxy."""
    import httpx

    info_url = base_url.rstrip("/") + "/model/info"
    headers = (
        {"Authorization": f"Bearer {api_key}"}
        if api_key and api_key != "dummy"
        else {}
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            r = await http.get(info_url, headers=headers)
            r.raise_for_status()
            data = r.json()
        result: dict[str, dict] = {}
        for entry in data.get("data", []):
            name = entry.get("model_name") or entry.get("id", "")
            info = entry.get("model_info") or {}
            if name:
                ctx = info.get("max_input_tokens") or info.get("max_tokens")
                inp = _fmt_cost(info.get("input_cost_per_token"))
                out = _fmt_cost(info.get("output_cost_per_token"))
                result[name] = {
                    "max_tokens": ctx,
                    "input_cost_per_1m": inp,
                    "output_cost_per_1m": out,
                }
        logger.debug(
            "Fetched model info from %s: %d entries", info_url, len(result)
        )
        return result
    except Exception as exc:
        logger.warning(
            "Failed to fetch model info from %s: %s", info_url, exc
        )
        return {}
