"""LLM call infrastructure — retry/backoff, model fallback, and tool result summarization."""

import asyncio
import logging
import re
from collections.abc import AsyncGenerator
from contextvars import ContextVar
from dataclasses import dataclass, field
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

    Retry logic applies only to the initial create() call. Mid-stream errors propagate.
    """
    last_fallback_info.set(None)

    try:
        stream = await _attempt_stream_with_retries(model, messages, tools_param, tool_choice, provider_id, model_params)
    except _RETRYABLE_ERRORS as primary_exc:
        from app.services.server_config import get_global_fallback_models

        effective_fallbacks = list(fallback_models or [])
        for gfb in get_global_fallback_models():
            effective_fallbacks.append(gfb)

        tried = {model}
        last_exc = primary_exc
        stream = None
        for fb in effective_fallbacks:
            fb_model = fb.get("model", "")
            if not fb_model or fb_model in tried:
                continue
            tried.add(fb_model)
            fb_provider = fb.get("provider_id") or provider_id
            logger.warning(
                "Stream: Model %s failed (%s: %s), attempting fallback %s",
                model, type(last_exc).__name__, last_exc, fb_model,
            )
            try:
                stream = await _attempt_stream_with_retries(
                    fb_model, messages, tools_param, tool_choice, fb_provider, model_params,
                )
                last_fallback_info.set(FallbackInfo(
                    original_model=model,
                    fallback_model=fb_model,
                    reason=type(primary_exc).__name__,
                    original_error=str(primary_exc)[:500],
                ))
                break
            except _RETRYABLE_ERRORS as fb_exc:
                last_exc = fb_exc
                continue
        if stream is None:
            raise last_exc

    accumulator = StreamAccumulator()
    async for chunk in stream:
        events, is_done = accumulator.feed(chunk)
        for event in events:
            yield event
        if is_done:
            break

    yield accumulator.build()


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
    try:
        return await _llm_call_with_retries(
            model, messages, tools_param, tool_choice, provider_id, model_params,
        )
    except _RETRYABLE_ERRORS as primary_exc:
        from app.services.server_config import get_global_fallback_models

        effective_fallbacks = list(fallback_models or [])
        # Append global catch-all list
        for gfb in get_global_fallback_models():
            effective_fallbacks.append(gfb)

        tried = {model}
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
            prev_content = merged[-1].get("content", "")
            cur_content = msg.get("content", "")
            # Only merge simple string content; skip complex (audio/multipart)
            if isinstance(prev_content, str) and isinstance(cur_content, str):
                merged[-1] = {**merged[-1], "content": prev_content + "\n\n" + cur_content}
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
