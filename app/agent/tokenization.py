"""Single source of truth for token counting.

Routes by provider type:

- ``anthropic`` / ``anthropic-compatible`` / ``anthropic-subscription``
  → :meth:`anthropic.AsyncAnthropic.messages.count_tokens` (free HTTP, ~50–150 ms,
  cached). Anthropic's tokenizer is closed-source; the official endpoint is the
  documented best practice.
- ``openai`` / ``openai-compatible`` / ``openai-subscription`` / ``litellm`` /
  ``ollama`` → ``tiktoken`` (in-process, no network). Falls back to
  ``o200k_base`` (gpt-4o family) when the exact model isn't in the tiktoken
  registry. For non-OpenAI tokenizers this drifts ~5–15 % vs. the true count
  but stays well within the budget reserve.
- Genuinely unknown provider type → chars / 3.5 with a one-shot WARNING per
  ``(provider_type, model)`` so the log makes the unmeasured route obvious.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


_ANTHROPIC_KINDS = {"anthropic", "anthropic-compatible", "anthropic-subscription"}
_TIKTOKEN_KINDS = {
    "openai",
    "openai-compatible",
    "openai-subscription",
    "litellm",
    "ollama",
}

_CACHE_TTL_SECONDS = 60.0
_CACHE_MAX_ENTRIES = 1024
_FALLBACK_CHARS_PER_TOKEN = 3.5
_NON_TEXT_PART_TOKEN_ESTIMATES: dict[str, int] = {
    "image_url": 256,
    "input_audio": 256,
}

# Cache: key → (expires_at_monotonic, value)
_cache: dict[tuple, tuple[float, int]] = {}
_cache_lock = asyncio.Lock()

# WARNING dedupe so the unknown-provider log fires once per (provider_type, model)
_warned: set[tuple[str, str]] = set()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenCount:
    tokens: int
    method: str  # "anthropic-api" | "tiktoken" | "chars-fallback"


async def count_text_tokens(
    text: str,
    *,
    model: str,
    provider_type: str | None = None,
    provider_id: str | None = None,
) -> int:
    """Count tokens in a plain string for a given model.

    Async because the Anthropic path makes an HTTP call. Cached by content hash
    + (provider_type, model) for ~60 s.
    """
    if not text:
        return 0
    return (
        await _count(
            kind=_resolve_kind(provider_type, provider_id),
            model=model,
            payload_key=("text", text),
            anthropic_messages=[{"role": "user", "content": text}],
            anthropic_system=None,
            anthropic_tools=None,
            tiktoken_text=text,
        )
    ).tokens


async def count_message_tokens(
    *,
    model: str,
    messages: list[dict[str, Any]],
    system: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    provider_type: str | None = None,
    provider_id: str | None = None,
) -> int:
    """Count tokens for an assembled messages list (incl. system + tools).

    For Anthropic, this is exact (the count_tokens API mirrors what the
    messages API will charge). For tiktoken paths, this sums per-message text
    + a per-message overhead (~3 tokens) and adds tool/system text.
    """
    kind = _resolve_kind(provider_type, provider_id)
    payload_key = ("msgs", _hash_messages(messages, system, tools))
    return (
        await _count(
            kind=kind,
            model=model,
            payload_key=payload_key,
            anthropic_messages=_to_anthropic_messages(messages),
            anthropic_system=system,
            anthropic_tools=tools,
            tiktoken_text=_messages_to_text(messages, system=system, tools=tools),
            tiktoken_message_count=len(messages),
        )
    ).tokens


def count_text_tokens_sync(text: str, model: str) -> int:
    """Synchronous helper: tiktoken or chars-fallback only.

    Used by code paths that can't go async (e.g. legacy estimators called from
    sync contexts). Anthropic accuracy is sacrificed for sync — callers that
    care should use :func:`count_text_tokens` instead.
    """
    if not text:
        return 0
    enc = _tiktoken_encoding(model)
    if enc is None:
        return max(1, int(len(text) / _FALLBACK_CHARS_PER_TOKEN))
    return len(enc.encode(text))


def estimate_content_tokens(content: Any) -> int:
    """Estimate tokens for message content that may include multimodal parts."""
    if content is None:
        return 0
    if isinstance(content, str):
        return estimate_tokens(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, str):
                total += estimate_tokens(part)
                continue
            if not isinstance(part, dict):
                total += estimate_tokens(str(part))
                continue
            part_type = str(part.get("type") or "")
            if part_type in {"text", "input_text"}:
                total += estimate_tokens(str(part.get("text") or ""))
                continue
            total += _NON_TEXT_PART_TOKEN_ESTIMATES.get(part_type, 64)
        return total
    return estimate_tokens(str(content))


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _resolve_kind(provider_type: str | None, provider_id: str | None) -> str:
    if provider_type:
        return provider_type
    if provider_id:
        try:
            from app.services.providers import get_provider

            row = get_provider(provider_id)
            if row is not None:
                return row.provider_type
        except Exception:
            logger.debug("provider lookup failed for %s", provider_id, exc_info=True)
    return ""


async def _count(
    *,
    kind: str,
    model: str,
    payload_key: tuple,
    anthropic_messages: list[dict[str, Any]],
    anthropic_system: str | None,
    anthropic_tools: list[dict[str, Any]] | None,
    tiktoken_text: str,
    tiktoken_message_count: int = 1,
) -> TokenCount:
    cache_key = (kind, model, payload_key)
    cached = await _cache_get(cache_key)
    if cached is not None:
        # Method tag isn't cached — recompute label cheaply
        return TokenCount(tokens=cached, method=_method_for(kind))

    if kind in _ANTHROPIC_KINDS:
        try:
            n = await _count_anthropic(
                model=model,
                messages=anthropic_messages,
                system=anthropic_system,
                tools=anthropic_tools,
            )
            await _cache_put(cache_key, n)
            return TokenCount(n, "anthropic-api")
        except Exception:
            logger.debug(
                "anthropic count_tokens failed for model=%s — falling back to tiktoken",
                model,
                exc_info=True,
            )

    if kind in _TIKTOKEN_KINDS or kind in _ANTHROPIC_KINDS:
        n = _count_tiktoken(tiktoken_text, model, tiktoken_message_count)
        if n is not None:
            await _cache_put(cache_key, n)
            return TokenCount(n, "tiktoken")

    if (kind, model) not in _warned:
        _warned.add((kind, model))
        logger.warning(
            "No native tokenizer for provider_type=%r model=%r — using chars/%.1f fallback",
            kind or "<unknown>",
            model,
            _FALLBACK_CHARS_PER_TOKEN,
        )
    n = max(1, int(len(tiktoken_text) / _FALLBACK_CHARS_PER_TOKEN))
    await _cache_put(cache_key, n)
    return TokenCount(n, "chars-fallback")


def _method_for(kind: str) -> str:
    if kind in _ANTHROPIC_KINDS:
        return "anthropic-api"
    if kind in _TIKTOKEN_KINDS:
        return "tiktoken"
    return "chars-fallback"


# --- Anthropic ---


async def _count_anthropic(
    *,
    model: str,
    messages: list[dict[str, Any]],
    system: str | None,
    tools: list[dict[str, Any]] | None,
) -> int:
    import anthropic

    client = _anthropic_client()
    kwargs: dict[str, Any] = {"model": model, "messages": messages}
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools

    resp = await client.messages.count_tokens(**kwargs)
    # SDK returns an object with .input_tokens; fall back to dict access.
    return int(getattr(resp, "input_tokens", None) or resp["input_tokens"])  # type: ignore[index]


_anthropic_singleton = None


def _anthropic_client():
    """Return a cached AsyncAnthropic client backed by the first Anthropic provider.

    Used only for count_tokens. We don't reuse the chat-completion adapter
    because it wraps the SDK behind an OpenAI-shaped surface that doesn't
    expose ``messages.count_tokens``.
    """
    global _anthropic_singleton
    if _anthropic_singleton is not None:
        return _anthropic_singleton

    import anthropic

    api_key = ""
    base_url = "https://api.anthropic.com"
    try:
        from app.services.providers import list_providers

        for row in list_providers():
            if row.provider_type in _ANTHROPIC_KINDS and row.is_enabled and row.api_key:
                api_key = row.api_key
                if row.base_url:
                    base_url = row.base_url
                break
    except Exception:
        logger.debug("provider registry unavailable for anthropic count_tokens", exc_info=True)

    _anthropic_singleton = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url)
    return _anthropic_singleton


def _to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Best-effort coercion of OpenAI-shaped messages → Anthropic shape.

    Only keeps user / assistant turns with string content. Tool messages are
    folded into the prior user turn as text since count_tokens doesn't need
    perfect tool-call fidelity to give a reasonable input_tokens figure.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content")
        if role not in {"user", "assistant"}:
            # System messages are passed via the `system` kwarg, not in messages.
            # Tool messages are skipped — count_tokens still gets a good total
            # because tool schemas are included via `tools` and the assistant
            # turn that referenced the tool is preserved.
            continue
        if isinstance(content, list):
            text_parts = [
                p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
            ]
            content = "".join(text_parts)
        if not isinstance(content, str) or not content:
            continue
        out.append({"role": role, "content": content})
    if not out:
        # count_tokens requires at least one message
        out.append({"role": "user", "content": ""})
    return out


# --- tiktoken ---


def _tiktoken_encoding(model: str):
    """Return a tiktoken encoding for *model* or None if tiktoken isn't installed."""
    try:
        import tiktoken
    except ImportError:
        return None
    # Strip provider prefix (matches context_budget._normalize_model_name)
    name = model.split("/", 1)[1] if "/" in model else model
    try:
        return tiktoken.encoding_for_model(name)
    except KeyError:
        try:
            return tiktoken.get_encoding("o200k_base")
        except Exception:
            return None


def _count_tiktoken(text: str, model: str, message_count: int) -> int | None:
    enc = _tiktoken_encoding(model)
    if enc is None:
        return None
    base = len(enc.encode(text))
    # OpenAI per-message overhead: ~3 tokens for the role/format wrapper.
    return base + (3 * max(0, message_count))


def _messages_to_text(
    messages: list[dict[str, Any]],
    *,
    system: str | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> str:
    """Flatten messages + system + tools into one string for tiktoken."""
    import json as _json

    parts: list[str] = []
    if system:
        parts.append(system)
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if isinstance(content, list):
            content = "".join(
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            )
        parts.append(f"{role}: {content}" if role else str(content))
    if tools:
        try:
            parts.append(_json.dumps(tools, separators=(",", ":")))
        except Exception:
            for t in tools:
                parts.append(str(t))
    return "\n".join(parts)


def _hash_messages(
    messages: list[dict[str, Any]],
    system: str | None,
    tools: list[dict[str, Any]] | None,
) -> str:
    h = hashlib.sha1(usedforsecurity=False)
    h.update((system or "").encode("utf-8", errors="ignore"))
    for m in messages:
        h.update(b"\x1f")
        h.update(str(m.get("role", "")).encode("utf-8", errors="ignore"))
        h.update(b"\x1e")
        c = m.get("content", "")
        if not isinstance(c, str):
            c = str(c)
        h.update(c.encode("utf-8", errors="ignore"))
    if tools:
        h.update(b"\x1d")
        for t in tools:
            h.update(str(t).encode("utf-8", errors="ignore"))
    return h.hexdigest()


# --- cache ---


async def _cache_get(key: tuple) -> int | None:
    async with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.monotonic():
            _cache.pop(key, None)
            return None
        return value


async def _cache_put(key: tuple, value: int) -> None:
    async with _cache_lock:
        if len(_cache) >= _CACHE_MAX_ENTRIES:
            # Evict oldest ~10% to keep insertion O(1)-ish without a full LRU.
            for old_key in list(_cache.keys())[: _CACHE_MAX_ENTRIES // 10]:
                _cache.pop(old_key, None)
        _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, value)


def _cache_clear() -> None:
    """Test helper — wipe the cache between assertions."""
    _cache.clear()
    _warned.clear()


# ---------------------------------------------------------------------------
# Compat shim — keeps ContextBudget happy while it migrates
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Sync chars/3.5 estimator — kept for hot-path call sites that can't go async.

    New code should prefer :func:`count_text_tokens_sync` (real tiktoken when
    available) or :func:`count_text_tokens` (real per-provider count).
    """
    if not text:
        return 0
    return max(1, int(len(text) / _FALLBACK_CHARS_PER_TOKEN))
