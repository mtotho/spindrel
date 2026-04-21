"""Context budget — tracks token consumption across assembly stages.

Provides a lightweight budget mechanism so context assembly can avoid
exceeding the model's context window.  No external dependencies (no tiktoken).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    """Content priority tiers for budget enforcement.

    When budget is tight, lower-priority content is trimmed first.
    """
    P0_PROTECTED = 0     # System prompt, user message, tool schemas — never trimmed
    P1_ESSENTIAL = 1     # Conversation history, MEMORY.md, compaction summary
    P2_IMPORTANT = 2     # Channel workspace files, pinned skills, daily logs
    P3_NICE_TO_HAVE = 3  # RAG skills, filesystem RAG, workspace RAG
    P4_EXPENDABLE = 4    # Tool index hints, delegate index, on-demand skill index


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------
# Re-export from the unified tokenization module so the hot path keeps a sync
# helper while everything else routes through the per-provider counter.
from app.agent.tokenization import estimate_tokens  # noqa: E402, F401


# ---------------------------------------------------------------------------
# Model context window resolution
# ---------------------------------------------------------------------------

# Fallback map for common models when we can't query the provider.
_MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "o1": 200_000,
    "o1-mini": 128_000,
    "o1-pro": 200_000,
    "o3": 200_000,
    "o3-mini": 200_000,
    "o4-mini": 200_000,
    # Anthropic
    "claude-opus-4-20250514": 200_000,
    "claude-sonnet-4-20250514": 200_000,
    "claude-3-7-sonnet-20250219": 200_000,
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-haiku-20241022": 200_000,
    "claude-3-opus-20240229": 200_000,
    "claude-3-sonnet-20240229": 200_000,
    "claude-3-haiku-20240307": 200_000,
    # Google
    "gemini-2.5-pro": 1_000_000,
    "gemini-2.5-flash": 1_000_000,
    "gemini-2.0-flash": 1_000_000,
    "gemini-1.5-pro": 2_000_000,
    "gemini-1.5-flash": 1_000_000,
}

# Aliases / prefixed model names that should map to known windows
_MODEL_ALIASES: dict[str, str] = {
    "claude-opus-4": "claude-opus-4-20250514",
    "claude-sonnet-4": "claude-sonnet-4-20250514",
}


def _normalize_model_name(model: str) -> str:
    """Strip common LiteLLM prefixes and normalize model name."""
    # Strip provider prefix (e.g. "openai/gpt-4o" → "gpt-4o",
    # "gemini/gemini-2.5-flash" → "gemini-2.5-flash")
    if "/" in model:
        model = model.split("/", 1)[1]
    return model


def get_model_context_window(model: str, provider_id: str | None = None) -> int:
    """Resolve the context window size for a model.

    Resolution order:
    1. ProviderModel DB row (if provider_id set and has context_window)
    2. Fallback map of known models
    3. Default from settings
    """
    from app.config import settings

    # 1. Try cached model info from providers (populated at startup / model list)
    try:
        from app.services.providers import _model_info_cache
        # Check provider-specific cache first, then .env fallback (provider_id=None)
        for pid in ([provider_id, None] if provider_id else [None]):
            provider_models = _model_info_cache.get(pid, {})
            if model in provider_models:
                ctx = provider_models[model].get("max_tokens")
                if ctx:
                    return int(ctx)
            # Also check without provider prefix
            norm = _normalize_model_name(model)
            if norm != model and norm in provider_models:
                ctx = provider_models[norm].get("max_tokens")
                if ctx:
                    return int(ctx)
    except Exception:
        pass

    # 2. Fallback map
    normalized = _normalize_model_name(model)

    # Check direct match
    if normalized in _MODEL_CONTEXT_WINDOWS:
        return _MODEL_CONTEXT_WINDOWS[normalized]

    # Check aliases
    if normalized in _MODEL_ALIASES:
        alias_target = _MODEL_ALIASES[normalized]
        if alias_target in _MODEL_CONTEXT_WINDOWS:
            return _MODEL_CONTEXT_WINDOWS[alias_target]

    # Fuzzy match: check if normalized starts with any known model key
    for known, window in _MODEL_CONTEXT_WINDOWS.items():
        if normalized.startswith(known):
            return window

    # 3. Default
    return settings.CONTEXT_BUDGET_DEFAULT_WINDOW


# ---------------------------------------------------------------------------
# Context Budget
# ---------------------------------------------------------------------------

@dataclass
class ContextBudget:
    """Tracks token consumption across context assembly stages."""

    total_tokens: int         # model context window
    reserve_tokens: int       # safety margin for output + overhead
    consumed_tokens: int = 0
    breakdown: dict[str, int] = field(default_factory=dict)

    @property
    def remaining(self) -> int:
        """Tokens available for further content injection."""
        return max(0, self.total_tokens - self.reserve_tokens - self.consumed_tokens)

    @property
    def available_budget(self) -> int:
        """Total usable budget (total minus reserve)."""
        return max(0, self.total_tokens - self.reserve_tokens)

    @property
    def utilization(self) -> float:
        """Fraction of available budget consumed (0.0 to 1.0+)."""
        avail = self.available_budget
        if avail <= 0:
            return 1.0
        return self.consumed_tokens / avail

    def consume(self, category: str, tokens: int) -> None:
        """Record token consumption for a category."""
        self.consumed_tokens += tokens
        self.breakdown[category] = self.breakdown.get(category, 0) + tokens

    def can_afford(self, tokens: int) -> bool:
        """Check if there's enough remaining budget for this content."""
        return tokens <= self.remaining

    def dynamic_top_k(self, configured_top_k: int) -> int:
        """Compute a reduced top_k for RAG stages based on remaining budget.

        Returns configured_top_k if plenty of budget, scales down to 1 when
        budget is tight, and 0 if nothing fits.
        """
        if self.remaining <= 0:
            return 0
        # Rough estimate: each RAG chunk is ~500 tokens
        affordable_chunks = max(0, self.remaining // 500)
        return min(configured_top_k, max(1, affordable_chunks)) if affordable_chunks > 0 else 0

    def to_dict(self) -> dict:
        """Serialize for trace events / observability."""
        return {
            "total_tokens": self.total_tokens,
            "reserve_tokens": self.reserve_tokens,
            "consumed_tokens": self.consumed_tokens,
            "remaining_tokens": self.remaining,
            "utilization": round(self.utilization, 3),
            "breakdown": dict(self.breakdown),
        }
