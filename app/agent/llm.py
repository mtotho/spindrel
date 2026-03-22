"""LLM call infrastructure — retry/backoff, model fallback, and tool result summarization."""

import asyncio
import logging

import openai

from app.config import settings

logger = logging.getLogger(__name__)

# All transient error types worth retrying.
_RETRYABLE_ERRORS = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
)


async def _llm_call(
    model: str,
    messages: list,
    tools_param: list | None,
    tool_choice: str | None,
    provider_id: str | None = None,
):
    """Call the LLM with retry logic for transient errors and optional model fallback.

    Retry strategy:
    - Rate limits (429): longer backoff via LLM_RATE_LIMIT_INITIAL_WAIT (default 90s).
    - Timeouts, connection errors, 5xx: shorter backoff via LLM_RETRY_INITIAL_WAIT (default 2s).
    - After all retries exhausted, if LLM_FALLBACK_MODEL is configured, attempt once
      with the fallback model before raising.
    """
    try:
        return await _llm_call_with_retries(
            model, messages, tools_param, tool_choice, provider_id,
        )
    except _RETRYABLE_ERRORS as exc:
        fallback_model = settings.LLM_FALLBACK_MODEL
        if not fallback_model or fallback_model == model:
            raise
        logger.warning(
            "Primary model %s failed after retries (%s: %s), attempting fallback model %s",
            model, type(exc).__name__, exc, fallback_model,
        )
        return await _llm_call_with_retries(
            fallback_model, messages, tools_param, tool_choice, provider_id,
        )


async def _llm_call_with_retries(
    model: str,
    messages: list,
    tools_param: list | None,
    tool_choice: str | None,
    provider_id: str | None = None,
):
    """Execute LLM call with exponential backoff on transient errors."""
    from app.services.providers import get_llm_client, record_usage

    client = get_llm_client(provider_id)
    max_retries = settings.LLM_MAX_RETRIES
    for attempt in range(max_retries + 1):
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools_param,
                tool_choice=tool_choice,
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
    input_content = content[:cap] + (f"\n[... {len(content) - cap:,} chars omitted]" if len(content) > cap else "")
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
