"""LLM call infrastructure — retry/backoff, model fallback, and tool result summarization."""

import asyncio
import logging
import re
from collections.abc import AsyncGenerator
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import openai

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Think-tag handling
# ---------------------------------------------------------------------------
# Models like DeepSeek/Qwen embed reasoning in <think>...</think> inside
# delta.content instead of using the reasoning_content attribute.  The parser
# below splits streaming text into content vs. thinking on-the-fly.

_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


class ThinkTagParser:
    """Streaming state machine that separates <think> blocks from content."""

    def __init__(self):
        self._in_think: bool = False
        self._buffer: str = ""  # held-back chars that might be a partial tag

    def feed(self, text: str) -> tuple[str, str]:
        """Process a chunk of text.  Returns (content_text, thinking_text)."""
        self._buffer += text
        content_out: list[str] = []
        thinking_out: list[str] = []

        while self._buffer:
            if self._in_think:
                idx = self._buffer.find(_THINK_CLOSE)
                if idx != -1:
                    # Emit everything before the close tag as thinking
                    thinking_out.append(self._buffer[:idx])
                    self._buffer = self._buffer[idx + len(_THINK_CLOSE):]
                    self._in_think = False
                else:
                    # Check if the buffer ends with a potential partial close tag
                    safe, held = self._split_at_potential_tag(self._buffer, _THINK_CLOSE)
                    if safe:
                        thinking_out.append(safe)
                    self._buffer = held
                    break
            else:
                idx = self._buffer.find(_THINK_OPEN)
                if idx != -1:
                    # Emit everything before the open tag as content
                    content_out.append(self._buffer[:idx])
                    self._buffer = self._buffer[idx + len(_THINK_OPEN):]
                    self._in_think = True
                else:
                    # Check if the buffer ends with a potential partial open tag
                    safe, held = self._split_at_potential_tag(self._buffer, _THINK_OPEN)
                    if safe:
                        content_out.append(safe)
                    self._buffer = held
                    break

        return "".join(content_out), "".join(thinking_out)

    def flush(self) -> tuple[str, str]:
        """Emit any remaining buffered text (call at end of stream)."""
        remaining = self._buffer
        self._buffer = ""
        if self._in_think:
            return "", remaining
        return remaining, ""

    @staticmethod
    def _split_at_potential_tag(text: str, tag: str) -> tuple[str, str]:
        """Split text into (safe_to_emit, held_back) based on partial tag match.

        If the end of *text* is a prefix of *tag*, hold it back.
        E.g. text="hello<th", tag="<think>" → ("hello", "<th")
        """
        # Check progressively shorter suffixes of text against prefixes of tag
        max_check = min(len(tag) - 1, len(text))
        for length in range(max_check, 0, -1):
            if text[-length:] == tag[:length]:
                return text[:-length], text[-length:]
        return text, ""


def strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from text (for non-streaming paths)."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)


@dataclass
class FallbackInfo:
    """Metadata about a fallback that occurred during _llm_call."""
    original_model: str
    fallback_model: str
    reason: str  # e.g. "EmptyChoicesError" or "RateLimitError"
    original_error: str  # truncated error message


# Set by _llm_call when a fallback is used; cleared before each call.
# The loop reads this after _llm_call returns to emit trace events.
last_fallback_info: ContextVar[FallbackInfo | None] = ContextVar("last_fallback_info", default=None)


# ---------------------------------------------------------------------------
# Circuit breaker — skip models that recently failed and needed fallback
# ---------------------------------------------------------------------------
# model -> (expires_at, fallback_model)
_model_cooldowns: dict[str, tuple[datetime, str]] = {}


def set_model_cooldown(model: str, fallback_model: str) -> None:
    """Record that *model* failed and *fallback_model* should be used until cooldown expires."""
    cooldown_sec = settings.LLM_FALLBACK_COOLDOWN_SECONDS
    if cooldown_sec <= 0:
        return
    expires = datetime.now(timezone.utc) + timedelta(seconds=cooldown_sec)
    _model_cooldowns[model] = (expires, fallback_model)
    logger.info("Circuit breaker: %s in cooldown until %s, using %s", model, expires.isoformat(), fallback_model)


def get_model_cooldown(model: str) -> str | None:
    """Return the fallback model if *model* is in cooldown, else None."""
    entry = _model_cooldowns.get(model)
    if entry is None:
        return None
    expires, fallback_model = entry
    if datetime.now(timezone.utc) >= expires:
        del _model_cooldowns[model]
        return None
    return fallback_model


def get_active_cooldowns() -> list[dict]:
    """Return all active cooldowns for the admin API."""
    now = datetime.now(timezone.utc)
    active = []
    expired_keys = []
    for model, (expires, fallback_model) in _model_cooldowns.items():
        if now >= expires:
            expired_keys.append(model)
        else:
            active.append({
                "model": model,
                "fallback_model": fallback_model,
                "expires_at": expires.isoformat(),
                "remaining_seconds": int((expires - now).total_seconds()),
            })
    for k in expired_keys:
        del _model_cooldowns[k]
    return active


def get_cooldown_expiry(model: str) -> datetime | None:
    """Return the cooldown expiry time for *model*, or None if not in cooldown."""
    entry = _model_cooldowns.get(model)
    if entry is None:
        return None
    expires, _ = entry
    if datetime.now(timezone.utc) >= expires:
        del _model_cooldowns[model]
        return None
    return expires


def clear_model_cooldown(model: str) -> bool:
    """Manually clear a model cooldown. Returns True if it was found."""
    return _model_cooldowns.pop(model, None) is not None


class EmptyChoicesError(Exception):
    """Raised when the LLM returns a response with an empty choices list."""
    pass


# All transient error types worth retrying.
_RETRYABLE_ERRORS = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
    EmptyChoicesError,
)


@dataclass
class AccumulatedMessage:
    """Fully accumulated message from a streaming LLM response."""
    role: str = "assistant"
    content: str | None = None
    tool_calls: list[dict] | None = None
    thinking_content: str | None = None
    usage: Any = None  # openai Usage object or None

    def to_msg_dict(self) -> dict:
        """Produce the same dict as msg.model_dump(exclude_none=True)."""
        d: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        return d


class StreamAccumulator:
    """Accumulates streaming chat completion chunks into events + final message."""

    def __init__(self):
        self._content_parts: list[str] = []
        self._thinking_parts: list[str] = []
        self._think_parser = ThinkTagParser()
        # tool_calls indexed by delta.index
        self._tool_calls: dict[int, dict] = {}
        self._usage: Any = None
        self._finish_reason: str | None = None

    def feed(self, chunk) -> tuple[list[dict], bool]:
        """Process one chunk. Returns (events_to_emit, is_done)."""
        events: list[dict] = []
        if not chunk.choices:
            # Usage-only chunk (final chunk with stream_options)
            if chunk.usage:
                self._usage = chunk.usage
            return events, False

        choice = chunk.choices[0]
        delta = choice.delta

        # Text content — route <think> blocks to thinking events
        if delta.content:
            content_text, thinking_text = self._think_parser.feed(delta.content)
            if content_text:
                self._content_parts.append(content_text)
                events.append({"type": "text_delta", "delta": content_text})
            if thinking_text:
                self._thinking_parts.append(thinking_text)
                events.append({"type": "thinking", "delta": thinking_text})

        # Thinking/reasoning content (provider-dependent attribute)
        reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
        if reasoning:
            self._thinking_parts.append(reasoning)
            events.append({"type": "thinking", "delta": reasoning})

        # Tool call deltas
        if delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in self._tool_calls:
                    self._tool_calls[idx] = {
                        "id": tc_delta.id or "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                tc = self._tool_calls[idx]
                if tc_delta.id:
                    tc["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        tc["function"]["name"] += tc_delta.function.name
                    if tc_delta.function.arguments:
                        tc["function"]["arguments"] += tc_delta.function.arguments

        if chunk.usage:
            self._usage = chunk.usage

        is_done = choice.finish_reason is not None
        if is_done:
            self._finish_reason = choice.finish_reason
            # Flush any remaining buffered text from the think-tag parser
            flush_content, flush_thinking = self._think_parser.flush()
            if flush_content:
                self._content_parts.append(flush_content)
                events.append({"type": "text_delta", "delta": flush_content})
            if flush_thinking:
                self._thinking_parts.append(flush_thinking)
                events.append({"type": "thinking", "delta": flush_thinking})
        return events, is_done

    def build(self) -> AccumulatedMessage:
        """Build the final accumulated message."""
        content = "".join(self._content_parts) if self._content_parts else None
        # Normalize whitespace-only content to None (e.g. "\n\n" after stripped think tags)
        if content is not None and not content.strip():
            content = None
        elif content is not None:
            content = content.strip()
        thinking = "".join(self._thinking_parts) if self._thinking_parts else None
        tool_calls = (
            [self._tool_calls[i] for i in sorted(self._tool_calls)]
            if self._tool_calls else None
        )
        return AccumulatedMessage(
            role="assistant",
            content=content,
            tool_calls=tool_calls,
            thinking_content=thinking,
            usage=self._usage,
        )


async def _consume_stream(stream) -> AsyncGenerator[dict | AccumulatedMessage, None]:
    """Consume a streaming response, yielding events then the final AccumulatedMessage."""
    accumulator = StreamAccumulator()
    async for chunk in stream:
        events, is_done = accumulator.feed(chunk)
        for event in events:
            yield event
        if is_done:
            break
    yield accumulator.build()


async def _llm_call_stream(
    model: str,
    messages: list,
    tools_param: list | None,
    tool_choice: str | None,
    provider_id: str | None = None,
    model_params: dict | None = None,
    fallback_models: list[dict] | None = None,
) -> AsyncGenerator[dict | AccumulatedMessage, None]:
    """Streaming LLM call with retry + fallback. Yields events then AccumulatedMessage last.

    Retry logic is inlined so retry/fallback status events can be yielded to
    the SSE stream, keeping Slack and other consumers informed during retries.
    """
    from app.agent.model_params import filter_model_params
    from app.services.providers import get_llm_client, requires_system_message_folding

    last_fallback_info.set(None)
    max_retries = settings.LLM_MAX_RETRIES

    def _is_non_transient_500(exc: openai.InternalServerError) -> bool:
        """Detect 500s that wrap non-transient upstream errors (e.g. LiteLLM wrapping a 400)."""
        msg = str(exc).lower()
        return any(k in msg for k in ("bad_request", "invalid params", "http_code\":\"400", "400"))

    async def _try_model(m: str, pid: str | None, mp: dict | None):
        """Attempt one model with retries. Returns stream or raises."""
        client = get_llm_client(pid)
        filtered = filter_model_params(m, mp or {})
        eff_msgs = messages
        if requires_system_message_folding(m):
            eff_msgs = _fold_system_messages(messages)
        return await client.chat.completions.create(
            model=m, messages=eff_msgs, tools=tools_param,
            tool_choice=tool_choice, stream=True,
            stream_options={"include_usage": True}, **filtered,
        )

    # --- Circuit breaker: skip model if in cooldown ---
    primary_exc = None
    stream = None
    cooldown_fb = get_model_cooldown(model)
    if cooldown_fb is not None:
        logger.info("Circuit breaker: skipping %s (in cooldown), using %s directly", model, cooldown_fb)
        yield {"type": "llm_cooldown_skip", "model": model, "using": cooldown_fb}
        try:
            stream = await _try_model(cooldown_fb, provider_id, model_params)
            last_fallback_info.set(FallbackInfo(
                original_model=model, fallback_model=cooldown_fb,
                reason="cooldown_skip", original_error="model in cooldown",
            ))
            async for ev in _consume_stream(stream):
                yield ev
            return
        except _RETRYABLE_ERRORS as exc:
            logger.warning("Cooldown fallback %s also failed: %s, skipping to fallback chain", cooldown_fb, exc)
            clear_model_cooldown(model)
            # Skip primary retries — go straight to fallback chain
            primary_exc = exc
            stream = None
            # Jump past the primary retry loop
            # (primary_exc is set, stream is None → fallback block runs)

    # --- Primary model with retries (skipped if cooldown already set primary_exc) ---
    if primary_exc is None:
        for attempt in range(max_retries + 1):
            try:
                stream = await _try_model(model, provider_id, model_params)
                break
            except openai.RateLimitError as exc:
                if attempt >= max_retries:
                    primary_exc = exc
                    break
                wait = settings.LLM_RATE_LIMIT_INITIAL_WAIT * (2 ** attempt)
                logger.warning("Stream LLM call rate limited (attempt %d/%d), waiting %ds...", attempt + 1, max_retries, wait)
                yield {"type": "llm_retry", "attempt": attempt + 1, "max_retries": max_retries,
                       "wait_seconds": wait, "reason": "rate_limited", "model": model}
                await asyncio.sleep(wait)
            except (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError) as exc:
                # Non-transient 500s (e.g. LiteLLM wrapping a 400) — skip retries, go to fallback
                if isinstance(exc, openai.InternalServerError) and _is_non_transient_500(exc):
                    logger.warning("Stream LLM call got non-transient 500 (%s), skipping retries", str(exc)[:200])
                    primary_exc = exc
                    break
                if attempt >= max_retries:
                    primary_exc = exc
                    break
                wait = settings.LLM_RETRY_INITIAL_WAIT * (2 ** attempt)
                logger.warning("Stream LLM call failed with %s (attempt %d/%d), waiting %.1fs...",
                               type(exc).__name__, attempt + 1, max_retries, wait)
                yield {"type": "llm_retry", "attempt": attempt + 1, "max_retries": max_retries,
                       "wait_seconds": wait, "reason": type(exc).__name__, "model": model}
                await asyncio.sleep(wait)

    # --- Fallback models ---
    if stream is None and primary_exc is not None:
        from app.services.server_config import get_global_fallback_models

        effective_fallbacks = list(fallback_models or [])
        for gfb in get_global_fallback_models():
            effective_fallbacks.append(gfb)

        tried = {model, cooldown_fb} if cooldown_fb else {model}
        last_exc = primary_exc
        for fb in effective_fallbacks:
            fb_model = fb.get("model", "")
            if not fb_model or fb_model in tried:
                continue
            tried.add(fb_model)
            fb_provider = fb.get("provider_id") or provider_id
            logger.warning("Stream: Model %s failed (%s: %s), attempting fallback %s",
                           model, type(last_exc).__name__, last_exc, fb_model)
            yield {"type": "llm_fallback", "from_model": model, "to_model": fb_model,
                   "reason": type(last_exc).__name__}

            for attempt in range(max_retries + 1):
                try:
                    stream = await _try_model(fb_model, fb_provider, model_params)
                    last_fallback_info.set(FallbackInfo(
                        original_model=model, fallback_model=fb_model,
                        reason=type(primary_exc).__name__,
                        original_error=str(primary_exc)[:500],
                    ))
                    set_model_cooldown(model, fb_model)
                    break
                except openai.RateLimitError as exc:
                    if attempt >= max_retries:
                        last_exc = exc
                        break
                    wait = settings.LLM_RATE_LIMIT_INITIAL_WAIT * (2 ** attempt)
                    logger.warning("Stream LLM call rate limited (attempt %d/%d), waiting %ds...", attempt + 1, max_retries, wait)
                    yield {"type": "llm_retry", "attempt": attempt + 1, "max_retries": max_retries,
                           "wait_seconds": wait, "reason": "rate_limited", "model": fb_model}
                    await asyncio.sleep(wait)
                except (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError) as exc:
                    if isinstance(exc, openai.InternalServerError) and _is_non_transient_500(exc):
                        logger.warning("Stream fallback %s got non-transient 500, skipping retries", fb_model)
                        last_exc = exc
                        break
                    if attempt >= max_retries:
                        last_exc = exc
                        break
                    wait = settings.LLM_RETRY_INITIAL_WAIT * (2 ** attempt)
                    logger.warning("Stream LLM call failed with %s (attempt %d/%d), waiting %.1fs...",
                                   type(exc).__name__, attempt + 1, max_retries, wait)
                    yield {"type": "llm_retry", "attempt": attempt + 1, "max_retries": max_retries,
                           "wait_seconds": wait, "reason": type(exc).__name__, "model": fb_model}
                    await asyncio.sleep(wait)
            if stream is not None:
                break

        if stream is None:
            raise last_exc

    if stream is None:
        if primary_exc:
            raise primary_exc
        raise openai.APITimeoutError("All LLM attempts failed")

    async for ev in _consume_stream(stream):
        yield ev


async def _attempt_stream_with_retries(
    model: str,
    messages: list,
    tools_param: list | None,
    tool_choice: str | None,
    provider_id: str | None = None,
    model_params: dict | None = None,
):
    """Retry the initial streaming create() call with exponential backoff."""
    from app.agent.model_params import filter_model_params
    from app.services.providers import get_llm_client, requires_system_message_folding

    client = get_llm_client(provider_id)
    filtered_params = filter_model_params(model, model_params or {})

    effective_messages = messages
    if requires_system_message_folding(model):
        effective_messages = _fold_system_messages(messages)

    max_retries = settings.LLM_MAX_RETRIES
    for attempt in range(max_retries + 1):
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=effective_messages,
                tools=tools_param,
                tool_choice=tool_choice,
                stream=True,
                stream_options={"include_usage": True},
                **filtered_params,
            )
            return stream
        except openai.RateLimitError:
            if attempt >= max_retries:
                raise
            wait = settings.LLM_RATE_LIMIT_INITIAL_WAIT * (2 ** attempt)
            logger.warning(
                "Stream LLM call rate limited (attempt %d/%d), waiting %ds...",
                attempt + 1, max_retries, wait,
            )
            await asyncio.sleep(wait)
        except (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError) as exc:
            # Non-transient 500 (e.g. upstream 400 wrapped by LiteLLM) — don't retry
            if isinstance(exc, openai.InternalServerError):
                msg = str(exc).lower()
                if any(k in msg for k in ("bad_request", "invalid params", "http_code\":\"400", "400")):
                    raise
            if attempt >= max_retries:
                raise
            wait = settings.LLM_RETRY_INITIAL_WAIT * (2 ** attempt)
            logger.warning(
                "Stream LLM call failed with %s (attempt %d/%d), waiting %.1fs...",
                type(exc).__name__, attempt + 1, max_retries, wait,
            )
            await asyncio.sleep(wait)


async def _llm_call(
    model: str,
    messages: list,
    tools_param: list | None,
    tool_choice: str | None,
    provider_id: str | None = None,
    model_params: dict | None = None,
    fallback_models: list[dict] | None = None,
):
    """Call the LLM with retry logic for transient errors and ordered fallback chain.

    Retry strategy:
    - Rate limits (429): longer backoff via LLM_RATE_LIMIT_INITIAL_WAIT (default 90s).
    - Timeouts, connection errors, 5xx: shorter backoff via LLM_RETRY_INITIAL_WAIT (default 2s).
    - After all retries exhausted on primary, try each fallback in order.
    - Global fallback list is appended after the caller's list.

    Resolution order: channel list > bot list > global list (override, not merge).
    Global list is always appended as a catch-all.
    """
    # Clear any previous fallback info
    last_fallback_info.set(None)

    # --- Circuit breaker: skip model if in cooldown ---
    cooldown_fb = get_model_cooldown(model)
    cooldown_exc = None
    if cooldown_fb is not None:
        logger.info("Circuit breaker: skipping %s (in cooldown), using %s directly", model, cooldown_fb)
        try:
            resp = await _llm_call_with_retries(
                cooldown_fb, messages, tools_param, tool_choice, provider_id, model_params,
            )
            last_fallback_info.set(FallbackInfo(
                original_model=model, fallback_model=cooldown_fb,
                reason="cooldown_skip", original_error="model in cooldown",
            ))
            return resp
        except _RETRYABLE_ERRORS as exc:
            # Clear stale cooldown and skip to fallback chain (don't retry broken primary)
            clear_model_cooldown(model)
            cooldown_exc = exc

    if cooldown_exc is None:
        try:
            return await _llm_call_with_retries(
                model, messages, tools_param, tool_choice, provider_id, model_params,
            )
        except _RETRYABLE_ERRORS as exc:
            cooldown_exc = exc

    primary_exc = cooldown_exc
    if primary_exc is not None:
        from app.services.server_config import get_global_fallback_models

        effective_fallbacks = list(fallback_models or [])
        # Append global catch-all list
        for gfb in get_global_fallback_models():
            effective_fallbacks.append(gfb)

        tried = {model, cooldown_fb} if cooldown_fb else {model}
        last_exc = primary_exc
        for fb in effective_fallbacks:
            fb_model = fb.get("model", "")
            if not fb_model or fb_model in tried:
                continue
            tried.add(fb_model)
            fb_provider = fb.get("provider_id") or provider_id
            logger.warning(
                "Model %s failed (%s: %s), attempting fallback %s",
                model, type(last_exc).__name__, last_exc, fb_model,
            )
            try:
                resp = await _llm_call_with_retries(
                    fb_model, messages, tools_param, tool_choice,
                    fb_provider, model_params,
                )
                last_fallback_info.set(FallbackInfo(
                    original_model=model,
                    fallback_model=fb_model,
                    reason=type(primary_exc).__name__,
                    original_error=str(primary_exc)[:500],
                ))
                set_model_cooldown(model, fb_model)
                return resp
            except _RETRYABLE_ERRORS as fb_exc:
                last_exc = fb_exc
                continue
        raise last_exc


def _fold_system_messages(messages: list) -> list:
    """Fold all system messages into the conversation for providers that reject role:system.

    Strategy:
    - Collect all system message content and merge into a single user message
      placed at the start of the conversation.
    - Preserve non-system messages in order.
    - Ensure strict role alternation (no consecutive same-role messages) by
      merging adjacent same-role messages with a newline separator.
    """
    system_parts: list[str] = []
    non_system: list[dict] = []
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                system_parts.append(content)
            elif isinstance(content, list):
                # Multimodal/list content — flatten to string to preserve it
                text = " ".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )
                if text.strip():
                    system_parts.append(text)
            # Empty/None content is intentionally skipped (no useful data)
        else:
            non_system.append(msg)

    result: list[dict] = []
    if system_parts:
        result.append({"role": "user", "content": "\n\n---\n\n".join(system_parts)})
    result.extend(non_system)

    # Enforce role alternation: merge consecutive same-role messages
    merged: list[dict] = []
    for msg in result:
        if merged and merged[-1]["role"] == msg["role"]:
            prev = merged[-1]
            prev_content = prev.get("content", "")
            cur_content = msg.get("content", "")

            # Never merge tool-result messages — each has a unique tool_call_id
            if msg.get("role") == "tool":
                merged.append(msg)
                continue

            # Only merge simple string content; skip complex (audio/multipart)
            if isinstance(prev_content, str) and isinstance(cur_content, str):
                combined = {**prev, "content": prev_content + "\n\n" + cur_content}
                # Preserve tool_calls from both assistant messages
                prev_tc = prev.get("tool_calls") or []
                cur_tc = msg.get("tool_calls") or []
                if prev_tc or cur_tc:
                    combined["tool_calls"] = list(prev_tc) + list(cur_tc)
                merged[-1] = combined
            else:
                merged.append(msg)
        else:
            merged.append(msg)
    return merged


async def _llm_call_with_retries(
    model: str,
    messages: list,
    tools_param: list | None,
    tool_choice: str | None,
    provider_id: str | None = None,
    model_params: dict | None = None,
):
    """Execute LLM call with exponential backoff on transient errors."""
    from app.agent.model_params import filter_model_params
    from app.services.providers import get_llm_client, record_usage, requires_system_message_folding

    client = get_llm_client(provider_id)
    filtered_params = filter_model_params(model, model_params or {})

    if requires_system_message_folding(model):
        messages = _fold_system_messages(messages)
    max_retries = settings.LLM_MAX_RETRIES
    for attempt in range(max_retries + 1):
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools_param,
                tool_choice=tool_choice,
                **filtered_params,
            )
            if not resp.choices:
                raise EmptyChoicesError(
                    f"LLM returned empty choices list (model={model}, "
                    f"finish_reason=n/a, id={getattr(resp, 'id', '?')})"
                )
            if resp.usage:
                record_usage(provider_id, resp.usage.total_tokens)
            return resp
        except openai.RateLimitError:
            if attempt >= max_retries:
                raise
            wait = settings.LLM_RATE_LIMIT_INITIAL_WAIT * (2 ** attempt)
            logger.warning(
                "LLM call rate limited (attempt %d/%d), waiting %ds before retry...",
                attempt + 1, max_retries, wait,
            )
            await asyncio.sleep(wait)
        except EmptyChoicesError as exc:
            if attempt >= max_retries:
                raise
            wait = settings.LLM_RETRY_INITIAL_WAIT * (2 ** attempt)
            logger.warning(
                "LLM returned empty choices (attempt %d/%d), waiting %.1fs before retry: %s",
                attempt + 1, max_retries, wait, exc,
            )
            await asyncio.sleep(wait)
        except (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError) as exc:
            if attempt >= max_retries:
                raise
            wait = settings.LLM_RETRY_INITIAL_WAIT * (2 ** attempt)
            label = type(exc).__name__
            logger.warning(
                "LLM call failed with %s (attempt %d/%d), waiting %.1fs before retry...",
                label, attempt + 1, max_retries, wait,
            )
            await asyncio.sleep(wait)


async def _summarize_tool_result(
    tool_name: str, content: str, model: str, max_tokens: int, provider_id: str | None = None
) -> str:
    """Summarize a large tool result to reduce context window usage. Falls back to original on error."""
    from app.services.providers import get_llm_client
    cap = 12000
    head = 8000
    tail = 4000
    if len(content) > cap:
        input_content = (
            content[:head]
            + f"\n\n[... {len(content) - head - tail:,} chars omitted ...]\n\n"
            + content[-tail:]
        )
    else:
        input_content = content
    prompt = (
        "Summarize this tool output concisely. "
        "Preserve: exit codes, errors, warnings, key values, file names, IDs, counts, actionable info. "
        "Omit: progress bars, verbose package lists, redundant log lines. Be brief.\n\n"
        f"Tool: {tool_name}\n<output>\n{input_content}\n</output>"
    )
    try:
        client = get_llm_client(provider_id)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        summary = resp.choices[0].message.content or content
        return f"[summarized from {len(content):,} chars]\n{summary}"
    except Exception:
        logger.warning("Tool result summarization failed for %s, using original", tool_name)
        return content
