"""LLM call infrastructure — retry/backoff, model fallback, and tool result summarization."""

import asyncio
import logging
from contextvars import ContextVar
from dataclasses import dataclass

import openai

from app.config import settings

logger = logging.getLogger(__name__)


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
