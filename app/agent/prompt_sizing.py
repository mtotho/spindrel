"""Cheap prompt-size helpers for model-visible chat messages."""
from __future__ import annotations

import json
from typing import Any

from app.agent.tokenization import estimate_content_tokens

_FALLBACK_CHARS_PER_TOKEN = 3.5


def estimate_chars_to_tokens(chars: int) -> int:
    """Estimate tokens from an already-known char count without allocating."""
    if chars <= 0:
        return 0
    return max(1, int(chars / _FALLBACK_CHARS_PER_TOKEN))


def message_prompt_chars(message: dict[str, Any]) -> int:
    """Approximate prompt chars for message content plus assistant tool calls."""
    content = message.get("content") or ""
    if isinstance(content, str):
        chars = len(content)
    elif isinstance(content, list):
        chars = sum(len(str(part)) for part in content)
    else:
        chars = len(str(content))

    tool_calls = message.get("tool_calls")
    if tool_calls:
        chars += len(json.dumps(tool_calls, separators=(",", ":"), default=str))
    return chars


def message_prompt_tokens(message: dict[str, Any]) -> int:
    """Estimate prompt tokens for a single message including tool calls."""
    tokens = estimate_content_tokens(message.get("content"))
    tool_calls = message.get("tool_calls")
    if tool_calls:
        tokens += estimate_chars_to_tokens(
            len(json.dumps(tool_calls, separators=(",", ":"), default=str))
        )
    return tokens


def messages_prompt_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(message_prompt_tokens(message) for message in messages)
