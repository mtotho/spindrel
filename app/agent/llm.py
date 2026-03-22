"""LLM call infrastructure — retry/backoff and tool result summarization."""

import asyncio
import logging

import openai

from app.config import settings

logger = logging.getLogger(__name__)


async def _llm_call(
    model: str,
    messages: list,
    tools_param: list | None,
    tool_choice: str | None,
    provider_id: str | None = None,
):
    """Call the LLM with exponential backoff on rate limit errors.

    Also retries on APITimeoutError: LiteLLM proxy may internally retry 429s for ~65s,
    causing the HTTP call to exceed the client timeout and surface as a timeout instead of
    a RateLimitError.
    """
    from app.services.providers import get_llm_client, record_usage
    client = get_llm_client(provider_id)
    max_retries = settings.LLM_RATE_LIMIT_RETRIES
    initial_wait = settings.LLM_RATE_LIMIT_INITIAL_WAIT
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
        except (openai.RateLimitError, openai.APITimeoutError) as exc:
            if attempt >= max_retries:
                raise
            wait = initial_wait * (2 ** attempt)
            label = "rate limited" if isinstance(exc, openai.RateLimitError) else "timed out (possible rate limit)"
            logger.warning(
                "LLM call %s (attempt %d/%d), waiting %ds before retry...",
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
