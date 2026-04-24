"""Ollama provider driver with full native API support."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, AsyncIterator

from openai import AsyncOpenAI

from app.config import settings

from .base import ProviderCapabilities, ProviderDriver

if TYPE_CHECKING:
    from app.db.models import ProviderConfig as ProviderConfigRow

logger = logging.getLogger(__name__)


def _base(config: ProviderConfigRow) -> str:
    """Return the raw Ollama base URL (no /v1 suffix)."""
    return (config.base_url or "http://localhost:11434").rstrip("/")


class OllamaDriver(ProviderDriver):
    provider_type = "ollama"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            list_models=True,
            pull_model=True,
            delete_model=True,
            model_info=True,
            running_models=True,
            requires_base_url=True,
            requires_api_key=False,
        )

    def make_client(self, config: ProviderConfigRow) -> AsyncOpenAI:
        kw: dict = {
            "base_url": f"{_base(config)}/v1",
            "api_key": "ollama",
            "timeout": settings.LLM_TIMEOUT,
            "max_retries": 0,
        }
        headers = self._extra_headers(config)
        if headers:
            kw["default_headers"] = headers
        return AsyncOpenAI(**kw)

    async def test_connection(
        self, api_key: str | None, base_url: str | None
    ) -> tuple[bool, str]:
        import httpx

        url = (base_url or "http://localhost:11434").rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=10.0) as hc:
                resp = await hc.get(f"{url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                count = len(data.get("models", []))
                return True, f"Connected ({count} models)"
        except Exception as exc:
            return False, str(exc)[:200]

    async def list_models(self, config: ProviderConfigRow) -> list[str]:
        import httpx

        url = _base(config)
        try:
            async with httpx.AsyncClient(timeout=10.0) as hc:
                resp = await hc.get(f"{url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return sorted(m["name"] for m in data.get("models", []))
        except Exception as exc:
            logger.warning("Ollama list_models failed: %s", exc)
            return []

    async def list_models_enriched(
        self, config: ProviderConfigRow
    ) -> list[dict]:
        import httpx

        url = _base(config)
        try:
            async with httpx.AsyncClient(timeout=10.0) as hc:
                resp = await hc.get(f"{url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
            result = []
            for m in data.get("models", []):
                name = m.get("name", "")
                details = m.get("details", {})
                size_bytes = m.get("size")
                result.append(
                    {
                        "id": name,
                        "display": name,
                        "size_bytes": size_bytes,
                        "parameter_size": details.get("parameter_size"),
                        "quantization": details.get("quantization_level"),
                        "family": details.get("family"),
                        "modified_at": m.get("modified_at"),
                    }
                )
            return sorted(result, key=lambda x: x["id"])
        except Exception as exc:
            logger.warning("Ollama list_models_enriched failed: %s", exc)
            return []

    async def pull_model(
        self, config: ProviderConfigRow, model_name: str
    ) -> AsyncIterator[dict]:
        import httpx

        url = _base(config)
        async with httpx.AsyncClient(timeout=None) as hc:
            async with hc.stream(
                "POST",
                f"{url}/api/pull",
                json={"name": model_name},
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.strip():
                        import json

                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            continue

    async def delete_model(
        self, config: ProviderConfigRow, model_name: str
    ) -> bool:
        import httpx

        url = _base(config)
        async with httpx.AsyncClient(timeout=10.0) as hc:
            resp = await hc.request(
                "DELETE", f"{url}/api/delete", json={"name": model_name}
            )
            resp.raise_for_status()
        return True

    async def get_model_info(
        self, config: ProviderConfigRow, model_name: str
    ) -> dict:
        import httpx

        url = _base(config)
        async with httpx.AsyncClient(timeout=10.0) as hc:
            resp = await hc.post(
                f"{url}/api/show", json={"name": model_name}
            )
            resp.raise_for_status()
            data = resp.json()
        return {
            "template": data.get("template"),
            "parameters": data.get("parameters"),
            "details": data.get("details", {}),
            "model_info": data.get("model_info", {}),
            "license": data.get("license"),
            "modelfile": data.get("modelfile"),
        }

    async def get_running_models(
        self, config: ProviderConfigRow
    ) -> list[dict]:
        import httpx

        url = _base(config)
        async with httpx.AsyncClient(timeout=10.0) as hc:
            resp = await hc.get(f"{url}/api/ps")
            resp.raise_for_status()
            data = resp.json()
        result = []
        for m in data.get("models", []):
            result.append(
                {
                    "name": m.get("name"),
                    "model": m.get("model"),
                    "size": m.get("size"),
                    "size_vram": m.get("size_vram"),
                    "digest": m.get("digest"),
                    "expires_at": m.get("expires_at"),
                    "details": m.get("details", {}),
                }
            )
        return result
