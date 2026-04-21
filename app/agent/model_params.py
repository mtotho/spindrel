"""Provider capability map and parameter definitions for per-bot LLM sampling parameters."""

from __future__ import annotations

# Heuristic fallback: provider families that do NOT support role: "system".
# Used when a model has no explicit DB entry.  The authoritative check is
# `requires_system_message_folding()` in app/services/providers.py.
_HEURISTIC_NO_SYS_MSG_FAMILIES: set[str] = {"minimax"}

# Heuristic fallback: specific model IDs known not to support function calling / tools.
_HEURISTIC_NO_TOOLS_MODELS: set[str] = {
    "gemini-2.0-flash-exp-image-generation",
    "imagen-3.0-generate-002",
}

# Substring patterns — if any pattern appears in the model ID, tools are not supported.
_HEURISTIC_NO_TOOLS_PATTERNS: list[str] = [
    "image-generation",
    # Gemini native image generation models (e.g. gemini-2.5-flash-image)
    "flash-image",
    "pro-image",
]


# Which OpenAI-style params each provider family supports.
#
# `thinking_budget` is a universal per-bot knob (integer token budget for
# extended thinking / reasoning). `_prepare_call_params` is responsible for
# translating it into the provider-specific request shape (Anthropic `thinking`
# block, Gemini `thinking_config`, LiteLLM `reasoning_effort`, etc.) — the raw
# value is NOT forwarded as a kwarg to the underlying SDK client.
MODEL_PARAM_SUPPORT: dict[str, set[str]] = {
    "openai": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty", "reasoning_effort", "thinking_budget"},
    "anthropic": {"temperature", "max_tokens", "thinking_budget"},
    "google": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty", "thinking_budget"},
    "gemini": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty", "thinking_budget"},
    "mistral": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty"},
    "deepseek": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty", "reasoning_effort", "thinking_budget"},
    "groq": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty"},
    "ollama": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty"},
    "xai": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty", "reasoning_effort", "thinking_budget"},
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
    {
        "name": "thinking_budget",
        "label": "Thinking budget",
        "description": "Token budget for extended thinking. 0 disables. Applies to Claude (4.x/3.7), Gemini 2.5, and other reasoning-capable models.",
        "type": "number",
        "min": 0,
        "max": 32000,
        "step": 256,
        "default": None,
    },
]
