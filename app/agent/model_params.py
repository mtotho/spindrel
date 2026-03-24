"""Provider capability map and parameter definitions for per-bot LLM sampling parameters."""

from __future__ import annotations

# Which OpenAI-style params each provider family supports.
MODEL_PARAM_SUPPORT: dict[str, set[str]] = {
    "openai": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty", "reasoning_effort"},
    "anthropic": {"temperature", "max_tokens"},
    "google": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty"},
    "gemini": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty"},
    "mistral": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty"},
    "deepseek": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty", "reasoning_effort"},
    "groq": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty"},
    "_default": {"temperature", "max_tokens"},
}


def get_provider_family(model: str) -> str:
    """Extract provider family from a LiteLLM model string (prefix before '/')."""
    if "/" in model:
        return model.split("/", 1)[0].lower()
    # Bare model names (e.g. gpt-4o) are openai
    return "openai"


def get_supported_params(model: str) -> set[str]:
    """Return the set of supported param names for the given model."""
    family = get_provider_family(model)
    return MODEL_PARAM_SUPPORT.get(family, MODEL_PARAM_SUPPORT["_default"])


def filter_model_params(model: str, params: dict) -> dict:
    """Strip unsupported params for the given model, returning a clean dict."""
    if not params:
        return {}
    supported = get_supported_params(model)
    return {k: v for k, v in params.items() if k in supported and v is not None}


# Metadata for UI rendering. Returned in editor-data so the frontend can
# build controls dynamically without hardcoding param knowledge.
PARAM_DEFINITIONS: list[dict] = [
    {
        "name": "temperature",
        "label": "Creativity",
        "description": "Higher = more creative and varied, lower = more focused and consistent",
        "type": "slider",
        "min": 0,
        "max": 2,
        "step": 0.05,
        "default": 1.0,
    },
    {
        "name": "max_tokens",
        "label": "Response length limit",
        "description": "Maximum number of tokens the model can generate per response",
        "type": "number",
        "min": 1,
        "max": 128000,
        "step": 1,
        "default": None,  # model default
    },
    {
        "name": "frequency_penalty",
        "label": "Word repetition penalty",
        "description": "Discourages reusing the same words and phrases",
        "type": "slider",
        "min": -2,
        "max": 2,
        "step": 0.05,
        "default": 0,
    },
    {
        "name": "presence_penalty",
        "label": "Topic repetition penalty",
        "description": "Encourages exploring new topics instead of revisiting ones already discussed",
        "type": "slider",
        "min": -2,
        "max": 2,
        "step": 0.05,
        "default": 0,
    },
    {
        "name": "reasoning_effort",
        "label": "Reasoning effort",
        "description": "How much effort the model spends thinking before responding (o-series, DeepSeek R1)",
        "type": "select",
        "options": ["low", "medium", "high"],
        "default": None,
    },
]
