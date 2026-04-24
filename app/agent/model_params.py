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
# `effort` is the user-facing reasoning knob (enum: off / low / medium / high).
# `translate_effort` resolves it into the provider-native request shape — the
# raw `effort` value is NOT forwarded as a kwarg to the underlying SDK client.
# `thinking_budget` remains as an advanced power-user override (integer token
# budget) for folks who want finer control than the enum gives; it only applies
# to families whose native API is budget-shaped (Anthropic, Gemini).
MODEL_PARAM_SUPPORT: dict[str, set[str]] = {
    "openai": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty", "effort", "reasoning_effort", "thinking_budget"},
    "anthropic": {"temperature", "max_tokens", "effort", "thinking_budget"},
    "google": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty", "effort", "thinking_budget"},
    "gemini": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty", "effort", "thinking_budget"},
    "mistral": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty"},
    "deepseek": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty", "effort", "reasoning_effort", "thinking_budget"},
    "groq": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty"},
    "ollama": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty"},
    "xai": {"temperature", "max_tokens", "frequency_penalty", "presence_penalty", "effort", "reasoning_effort", "thinking_budget"},
    "_default": {"temperature", "max_tokens"},
}


# Canonical effort enum. "off" disables reasoning entirely; the rest map
# per family in `translate_effort`.
EFFORT_LEVELS: tuple[str, ...] = ("off", "low", "medium", "high")

# Anthropic / Gemini use an integer token budget. These are the default
# thinking_budget values for each enum level; if the user set an explicit
# `thinking_budget` in bot.model_params it overrides these for their family.
_EFFORT_BUDGET_TOKENS: dict[str, int] = {
    "off": 0,
    "low": 2048,
    "medium": 8192,
    "high": 16384,
}


def translate_effort(model: str, effort: str | None, *, explicit_budget: int | None = None) -> dict:
    """Translate the user-facing `effort` enum into provider-native kwargs.

    Single source of truth for reasoning translation — ``_prepare_call_params``
    must not re-branch on provider family.

    Returns a dict of kwargs to merge into the outgoing request. Empty dict
    means "no reasoning config" (either because effort is unset/off or because
    the model's family doesn't support it).

    `explicit_budget` is the advanced-user `thinking_budget` override from
    ``bot.model_params``. For budget-shaped families (anthropic, gemini) it
    wins over the enum-derived default so power users keep their precision.
    For effort-shaped families (openai, xai, deepseek) it is ignored — the
    enum drives the effort string directly.
    """
    if not effort or effort not in EFFORT_LEVELS or effort == "off":
        return {}

    family = get_provider_family(model)
    if "effort" not in MODEL_PARAM_SUPPORT.get(family, MODEL_PARAM_SUPPORT["_default"]):
        return {}

    if family == "anthropic":
        budget = explicit_budget if explicit_budget is not None and explicit_budget > 0 else _EFFORT_BUDGET_TOKENS[effort]
        return {"thinking_budget": budget}

    if family in ("gemini", "google"):
        budget = explicit_budget if explicit_budget is not None and explicit_budget > 0 else _EFFORT_BUDGET_TOKENS[effort]
        return {
            "extra_body": {
                "thinking_config": {
                    "include_thoughts": True,
                    "thinking_budget": budget,
                },
            },
        }

    if family in ("openai", "xai", "deepseek"):
        # Both chat.completions reasoning models and the OpenAI Responses API
        # (Codex/gpt-5-*) accept `reasoning_effort`. The Responses adapter
        # translates it into `body.reasoning.effort` on the wire.
        return {"reasoning_effort": effort}

    return {}


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


_REASONING_PARAMS: frozenset[str] = frozenset(
    {"effort", "reasoning_effort", "thinking_budget"}
)


def filter_model_params(model: str, params: dict) -> dict:
    """Strip unsupported params for the given model, returning a clean dict.

    Two layers of gating:
    1. Family heuristic (``MODEL_PARAM_SUPPORT``) — drops params the provider
       family is known not to accept.
    2. Per-model reasoning flag (``supports_reasoning`` DB column) — drops
       ``effort`` / ``reasoning_effort`` / ``thinking_budget`` for models the
       admin has not marked as reasoning-capable. Prevents the silent-drop
       footgun where a user sets effort on a non-thinking model (e.g. gpt-4o)
       and gets no feedback.
    """
    if not params:
        return {}
    supported = get_supported_params(model)
    result = {k: v for k, v in params.items() if k in supported and v is not None}
    if result and any(k in result for k in _REASONING_PARAMS):
        # Local import avoids an import cycle: providers.py imports model_params.
        from app.services.providers import supports_reasoning as _supports_reasoning
        if not _supports_reasoning(model):
            for key in _REASONING_PARAMS:
                result.pop(key, None)
    return result


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
        "name": "effort",
        "label": "Reasoning effort",
        "description": "How hard the model thinks. Applies to Claude, Gemini 2.5, o-series, DeepSeek R1, Codex / gpt-5 — translated per provider.",
        "type": "select",
        "options": ["off", "low", "medium", "high"],
        "default": None,
    },
    {
        "name": "reasoning_effort",
        "label": "Reasoning effort (raw, advanced)",
        "description": "Direct pass-through of the OpenAI-style reasoning_effort string. Prefer the Reasoning effort enum above — this field is kept so bots with existing reasoning_effort values in their config keep working.",
        "type": "select",
        "options": ["low", "medium", "high"],
        "default": None,
        "advanced": True,
    },
    {
        "name": "thinking_budget",
        "label": "Thinking budget (advanced)",
        "description": "Override the effort enum with an explicit token budget. Only applies to budget-shaped families (Claude, Gemini). Leave blank to use the effort preset.",
        "type": "number",
        "min": 0,
        "max": 32000,
        "step": 256,
        "default": None,
        "advanced": True,
    },
]
