"""Provider driver registry.

Each provider type has a stateless singleton driver that handles
type-specific operations (client construction, connection testing,
model listing, etc.).
"""

from __future__ import annotations

from .anthropic_driver import AnthropicCompatibleDriver, AnthropicDriver
from .base import ProviderCapabilities, ProviderDriver
from .litellm_driver import LiteLLMDriver
from .ollama_driver import OllamaDriver
from .openai_driver import OpenAICompatibleDriver, OpenAIDriver

__all__ = [
    "ProviderCapabilities",
    "ProviderDriver",
    "get_driver",
    "DRIVER_REGISTRY",
    "PROVIDER_TYPES",
]

DRIVER_REGISTRY: dict[str, ProviderDriver] = {
    "litellm": LiteLLMDriver(),
    "openai": OpenAIDriver(),
    "openai-compatible": OpenAICompatibleDriver(),
    "anthropic": AnthropicDriver(),
    "anthropic-compatible": AnthropicCompatibleDriver(),
    "ollama": OllamaDriver(),
}

PROVIDER_TYPES: list[str] = list(DRIVER_REGISTRY.keys())

# Fallback for unknown types — treats them as OpenAI-compatible (most common)
_FALLBACK_DRIVER = OpenAICompatibleDriver()

logger = __import__("logging").getLogger(__name__)


def get_driver(provider_type: str) -> ProviderDriver:
    """Return the driver singleton for a provider type.

    Unknown types fall back to OpenAI-compatible with a warning instead of
    crashing, so providers with custom/legacy types still work.
    """
    driver = DRIVER_REGISTRY.get(provider_type)
    if driver is None:
        logger.warning(
            "Unknown provider type %r — falling back to openai-compatible driver. "
            "Valid types: %s",
            provider_type,
            PROVIDER_TYPES,
        )
        return _FALLBACK_DRIVER
    return driver
