"""Prompt caching: Anthropic cache_control breakpoints for Claude models.

Adds `cache_control: {"type": "ephemeral"}` markers to system messages,
enabling Anthropic's prompt caching. This significantly reduces cost on
multi-turn conversations where the system prompt + tools are repeated.

For OpenAI models, caching is automatic for >1024 token prefixes — no code needed.
For non-Anthropic/non-OpenAI models, this module is a no-op.
"""
from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)

# Max breakpoints Anthropic allows per request
_MAX_BREAKPOINTS = 4

# Rough chars-per-token estimate for threshold checking
_CHARS_PER_TOKEN = 4


def should_apply_cache_control(model: str, provider_id: str | None = None) -> bool:
    """Determine if cache_control breakpoints should be applied.

    Authoritative source: ``provider_models.supports_prompt_caching`` (DB column,
    cached in ``app/services/providers.py``). Replaces the prior string sniff
    on ``"claude" in model.lower()`` which missed MiniMax-via-anthropic-compatible
    and any non-claude-named cache-supporting model the admin had in the DB.

    Falls back to the provider-type heuristic for legacy bots that haven't yet
    been seeded into ``provider_models`` (older deployments where some bot's
    ``model`` is set to a string the registry doesn't know about).
    """
    if not settings.PROMPT_CACHE_ENABLED:
        return False

    try:
        from app.services.providers import (
            supports_prompt_caching as _supports_prompt_caching,
        )
        if _supports_prompt_caching(model, provider_id):
            return True
    except Exception:
        pass

    if provider_id:
        try:
            from app.services.providers import _registry
            provider = _registry.get(provider_id)
            if provider and provider.provider_type in ("anthropic", "anthropic-compatible"):
                return True
        except Exception:
            pass

    return False


def apply_cache_breakpoints(messages: list[dict]) -> list[dict]:
    """Add cache_control breakpoints to system messages.

    Returns a new list (shallow copy of messages) with strategic system messages
    converted to content-block format with cache_control markers.

    Breakpoint placement strategy (up to _MAX_BREAKPOINTS):
    1. First system message (bot system prompt — most stable)
    2. Last system message before conversation starts (tool list, final context)
    3. Midpoint system message (if enough messages exist)
    4. Any remaining large system messages

    Messages shorter than PROMPT_CACHE_MIN_TOKENS are skipped.
    """
    if not messages:
        return messages

    # Find system message indices
    sys_indices = [
        i for i, msg in enumerate(messages)
        if msg.get("role") == "system"
        and isinstance(msg.get("content"), str)
        and len(msg["content"]) >= settings.PROMPT_CACHE_MIN_TOKENS * _CHARS_PER_TOKEN
    ]

    if not sys_indices:
        return messages

    # Select breakpoint positions
    breakpoint_indices: list[int] = []

    if sys_indices:
        # First system message (most stable — system prompt)
        breakpoint_indices.append(sys_indices[0])

    if len(sys_indices) >= 2:
        # Last system message (tool schemas, final RAG context)
        breakpoint_indices.append(sys_indices[-1])

    if len(sys_indices) >= 4:
        # Midpoint
        mid = sys_indices[len(sys_indices) // 2]
        if mid not in breakpoint_indices:
            breakpoint_indices.append(mid)

    # Fill remaining slots with large system messages not yet selected
    if len(breakpoint_indices) < _MAX_BREAKPOINTS:
        remaining = [
            (i, len(messages[i].get("content", "")))
            for i in sys_indices
            if i not in breakpoint_indices
        ]
        remaining.sort(key=lambda x: x[1], reverse=True)
        for idx, _size in remaining:
            if len(breakpoint_indices) >= _MAX_BREAKPOINTS:
                break
            breakpoint_indices.append(idx)

    if not breakpoint_indices:
        return messages

    # Shallow copy and convert selected messages to content-block format
    result = list(messages)
    for idx in breakpoint_indices:
        msg = result[idx]
        content = msg["content"]
        result[idx] = {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": content,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }

    logger.debug(
        "Applied %d cache breakpoints at message indices: %s",
        len(breakpoint_indices), breakpoint_indices,
    )
    return result
