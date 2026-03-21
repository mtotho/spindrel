import asyncio
import json
import logging
import time
import traceback
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import openai

from app.agent.bots import BotConfig
from app.agent.context import set_agent_context, set_ephemeral_delegates
from app.agent.memory import retrieve_memories
from app.agent.knowledge import retrieve_knowledge
from app.agent.message_utils import (
    _AUDIO_TRANSCRIPT_INSTRUCTION,
    _all_tool_schemas_by_name,
    _build_audio_user_message,
    _build_user_message_content,
    _event_with_compaction_tag,
    _extract_client_actions,
    _extract_transcript,
    _merge_tool_schemas,
)
from app.agent.pending import CLIENT_TOOL_TIMEOUT, create_pending
from app.agent.rag import retrieve_context, fetch_skill_chunks_by_id
from app.agent.tags import resolve_tags
from app.agent.recording import _record_tool_call, _record_trace_event
from app.agent.tools import retrieve_tools
from app.config import settings
from app.tools.client_tools import get_client_tool_schemas, is_client_tool
from app.tools.mcp import call_mcp_tool, fetch_mcp_tools, get_mcp_server_for_tool, is_mcp_tool
from app.tools.local.memory import call_memory_tool
from app.tools.registry import call_local_tool, get_local_tool_schemas, is_local_tool
from app.tools.local.persona import call_persona_tool
from app.tools.local.knowledge import call_knowledge_tool

logger = logging.getLogger(__name__)

_SYS_MSG_PREFIXES: list[tuple[str, str]] = [
    ("Current time:", "sys:datetime"),
    ("Tagged skill context", "sys:tagged_skills"),
    ("Tagged knowledge", "sys:tagged_knowledge"),
    ("Available skills (use get_skill", "sys:skill_index"),
    ("Relevant context:\n", "sys:skill_context"),
    ("Available sub-agents", "sys:delegate_index"),
    ("Relevant memories from past", "sys:memory"),
    ("Pinned knowledge", "sys:pinned_knowledge"),
    ("Relevant knowledge:\n", "sys:knowledge"),
    ("Relevant code/files", "sys:fs_context"),
    ("Available tools (not yet loaded", "sys:tool_index"),
    ("Active plans for this session:", "sys:plans"),
    ("You must respond to the user", "sys:forced_response"),
    ("You have used too many tool calls", "sys:max_iterations"),
    ("[TRANSCRIPT_INSTRUCTION]", "sys:audio"),
]


def _CLASSIFY_SYS_MSG(content: str) -> str:
    for prefix, label in _SYS_MSG_PREFIXES:
        if content.startswith(prefix):
            return label
    return "sys:system_prompt"


def _trace(msg: str, *args: Any) -> None:
    """Log a single-line agent trace when AGENT_TRACE is enabled (no JSON)."""
    if settings.AGENT_TRACE:
        logger.info("[agent] " + msg, *args)

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


@dataclass
class RunResult:
    response: str = ""
    transcript: str = ""
    client_actions: list[dict] = field(default_factory=list)


async def run_agent_tool_loop(
    messages: list[dict],
    bot: BotConfig,
    session_id: uuid.UUID | None = None,
    client_id: str | None = None,
    *,
    model_override: str | None = None,
    turn_start: int = 0,
    native_audio: bool = False,
    user_msg_index: int | None = None,
    compaction: bool = False,
    pre_selected_tools: list[dict[str, Any]] | None = None,
    correlation_id: uuid.UUID | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Single agent tool loop: LLM + tool calls until final response. Caller builds messages and sets context.
    When compaction=True, every yielded event gets "compaction": True.
    """
    model = model_override or bot.model
    provider_id = bot.model_provider_id

    # Effective tool result summarization settings (bot-level overrides global)
    _trc = bot.tool_result_config or {}
    _eff_summarize_enabled: bool = _trc["enabled"] if "enabled" in _trc else settings.TOOL_RESULT_SUMMARIZE_ENABLED
    _eff_summarize_threshold: int = _trc.get("threshold") or settings.TOOL_RESULT_SUMMARIZE_THRESHOLD
    _eff_summarize_model: str = _trc.get("model") or settings.TOOL_RESULT_SUMMARIZE_MODEL or model
    _eff_summarize_max_tokens: int = _trc.get("max_tokens") or settings.TOOL_RESULT_SUMMARIZE_MAX_TOKENS
    _eff_summarize_exclude: set[str] = set(settings.TOOL_RESULT_SUMMARIZE_EXCLUDE_TOOLS) | set(_trc.get("exclude_tools") or [])

    if pre_selected_tools is not None:
        all_tools = list(pre_selected_tools)
    else:
        local_schemas = get_local_tool_schemas(bot.local_tools)
        mcp_schemas = await fetch_mcp_tools(bot.mcp_servers)
        client_schemas = get_client_tool_schemas(bot.client_tools)
        all_tools = local_schemas + mcp_schemas + client_schemas
        # Auto-inject get_skill when bot has skills configured (and tool not already included)
        if bot.skills and not any(
            t.get("function", {}).get("name") == "get_skill" for t in all_tools
        ):
            skill_schemas = get_local_tool_schemas(["get_skill"])
            all_tools = all_tools + skill_schemas
    tools_param = all_tools if all_tools else None
    tool_choice = "auto" if tools_param else None

    logger.debug("Tools available: %s", [t["function"]["name"] for t in all_tools] if all_tools else "(none)")

    transcript_emitted = False
    embedded_client_actions: list[dict] = []

    try:
        for iteration in range(settings.AGENT_MAX_ITERATIONS):
            logger.debug("--- Iteration %d ---", iteration + 1)
            logger.debug("Calling LLM (%s) with %d messages", model, len(messages))

            if correlation_id is not None:
                _breakdown: dict[str, dict] = {}
                for _m in messages:
                    _role = _m.get("role", "?")
                    _content = _m.get("content") or ""
                    _chars = sum(len(str(p)) for p in _content) if isinstance(_content, list) else len(_content)
                    if _role == "assistant" and _m.get("tool_calls"):
                        _chars += sum(len(str(tc)) for tc in _m["tool_calls"])
                    _key = _role
                    if _role == "system" and isinstance(_content, str):
                        _key = _CLASSIFY_SYS_MSG(_content)
                    if _key not in _breakdown:
                        _breakdown[_key] = {"count": 0, "chars": 0}
                    _breakdown[_key]["count"] += 1
                    _breakdown[_key]["chars"] += _chars
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="context_breakdown",
                    data={
                        "breakdown": _breakdown,
                        "total_messages": len(messages),
                        "total_chars": sum(v["chars"] for v in _breakdown.values()),
                        "iteration": iteration + 1,
                    },
                ))

            # TPM rate limit check: yield wait event and sleep if needed
            from app.services.providers import check_rate_limit
            _est_tokens = sum(
                len(str(m.get("content") or "")) // 4 for m in messages
            )
            _wait = check_rate_limit(provider_id, _est_tokens)
            if _wait:
                logger.info("Provider TPM limit: waiting %ds before LLM call", _wait)
                yield _event_with_compaction_tag(
                    {"type": "rate_limit_wait", "wait_seconds": _wait, "provider_id": provider_id or ""},
                    compaction,
                )
                await asyncio.sleep(_wait)

            response = await _llm_call(model, messages, tools_param, tool_choice, provider_id=provider_id)
            msg = response.choices[0].message
            msg_dict = msg.model_dump(exclude_none=True)
            messages.append(msg_dict)

            if response.usage:
                logger.debug(
                    "Token usage: prompt=%d completion=%d total=%d",
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                    response.usage.total_tokens,
                )
                if correlation_id is not None:
                    asyncio.create_task(_record_trace_event(
                        correlation_id=correlation_id,
                        session_id=session_id,
                        bot_id=bot.id,
                        client_id=client_id,
                        event_type="token_usage",
                        data={
                            "prompt_tokens": response.usage.prompt_tokens,
                            "completion_tokens": response.usage.completion_tokens,
                            "total_tokens": response.usage.total_tokens,
                            "iteration": iteration + 1,
                        },
                    ))

            if not msg.tool_calls:
                text = msg.content or ""
                _trace("✓ response (%d chars)", len(text))

                if not text.strip():
                    logger.warning("LLM response was empty. Forcing a response...")
                    messages.append({
                        "role": "system",
                        "content": "You must respond to the user. Write a response now."
                    })
                    try:
                        # Anthropic (via LiteLLM) rejects requests that include tool turns in
                        # `messages` unless `tools=` is also sent; use tool_choice=none so we
                        # only get a plain assistant reply.
                        retry_kw: dict[str, Any] = {"model": model, "messages": messages}
                        if tools_param is not None:
                            retry_kw["tools"] = tools_param
                            retry_kw["tool_choice"] = "none"
                        from app.services.providers import get_llm_client as _get_client
                        retry = await _get_client(provider_id).chat.completions.create(**retry_kw)
                        text = retry.choices[0].message.content or ""
                        messages.append(retry.choices[0].message.model_dump(exclude_none=True))
                    except Exception as exc:
                        logger.error("Forced-response retry failed: %s", exc)
                        if correlation_id is not None:
                            asyncio.create_task(_record_trace_event(
                                correlation_id=correlation_id,
                                session_id=session_id,
                                bot_id=bot.id,
                                client_id=client_id,
                                event_type="llm_error",
                                event_name="forced_response_retry",
                                data={"message": str(exc)[:2000]},
                            ))
                        text = "(I encountered an error generating a response. Please try again.)"
                        messages.append({"role": "assistant", "content": text})

                if native_audio and user_msg_index is not None and not transcript_emitted:
                    transcript, text = _extract_transcript(text)
                    messages[-1]["content"] = text
                    yield _event_with_compaction_tag({"type": "transcript", "text": transcript}, compaction)
                    if transcript:
                        logger.info("Audio transcript: %r", transcript[:100])
                        messages[user_msg_index] = {"role": "user", "content": transcript}
                    else:
                        logger.warning("Native audio response contained no transcript tags")
                        messages[user_msg_index] = {"role": "user", "content": "[inaudible]"}
                    transcript_emitted = True

                logger.info("Final response (%d chars): %r", len(text), text[:120])
                if correlation_id is not None and not compaction:
                    asyncio.create_task(_record_trace_event(
                        correlation_id=correlation_id,
                        session_id=session_id,
                        bot_id=bot.id,
                        client_id=client_id,
                        event_type="response",
                        data={"text": text[:500], "full_length": len(text)},
                    ))
                yield _event_with_compaction_tag({
                    "type": "response",
                    "text": text,
                    "client_actions": (
                        _extract_client_actions(messages, turn_start) + embedded_client_actions
                    ),
                }, compaction)
                return

            if native_audio and user_msg_index is not None and not transcript_emitted and msg.content:
                transcript, _ = _extract_transcript(msg.content)
                if transcript:
                    logger.info("Audio transcript (from tool-call response): %r", transcript[:100])
                    yield _event_with_compaction_tag({"type": "transcript", "text": transcript}, compaction)
                    messages[user_msg_index] = {"role": "user", "content": transcript}
                    transcript_emitted = True

            logger.info("LLM requested %d tool call(s)", len(msg.tool_calls))

            for tc in msg.tool_calls:
                name = tc.function.name
                args = tc.function.arguments
                logger.info("Tool call: %s", name)
                logger.debug("Tool call %s args: %s", name, args)

                _trace("→ %s", name)
                yield _event_with_compaction_tag({"type": "tool_start", "tool": name}, compaction)

                t0 = time.monotonic()
                _tc_type = "local"
                _tc_server: str | None = None

                if is_client_tool(name):
                    _tc_type = "client"
                    request_id = str(uuid.uuid4())
                    try:
                        tool_args = json.loads(args) if args else {}
                    except (json.JSONDecodeError, TypeError):
                        tool_args = {}
                    yield _event_with_compaction_tag({
                        "type": "tool_request",
                        "request_id": request_id,
                        "tool": name,
                        "arguments": tool_args,
                    }, compaction)
                    future = create_pending(request_id)
                    try:
                        result = await asyncio.wait_for(future, timeout=CLIENT_TOOL_TIMEOUT)
                    except asyncio.TimeoutError:
                        logger.warning("Client tool %s timed out (request %s)", name, request_id)
                        result = json.dumps({"error": "Client did not respond in time"})
                elif is_local_tool(name):
                    _tc_type = "local"
                    if name in (
                        "search_memories",
                        "save_memory",
                        "purge_memory",
                        "merge_memories",
                    ) and session_id and client_id:
                        result = await call_memory_tool(
                            name,
                            args or "{}",
                            session_id,
                            client_id,
                            bot.id,
                            bot.memory,
                            correlation_id=correlation_id,
                        )
                    elif name in ("update_persona", "append_to_persona"):
                        result = await call_persona_tool(name, args or "{}", bot.id)
                    elif name in (
                        "upsert_knowledge",
                        "get_knowledge",
                        "search_knowledge",
                        "list_knowledge_bases",
                        "append_to_knowledge",
                        "pin_knowledge",
                        "unpin_knowledge",
                        "set_knowledge_similarity_threshold",
                    ) and client_id:
                        result = await call_knowledge_tool(
                            name,
                            args or "{}",
                            bot.id,
                            client_id,
                            session_id=session_id,
                            fallback_threshold=settings.KNOWLEDGE_SIMILARITY_THRESHOLD,
                        )
                    else:
                        result = await call_local_tool(name, args)
                elif is_mcp_tool(name):
                    _tc_type = "mcp"
                    _tc_server = get_mcp_server_for_tool(name)
                    result = await call_mcp_tool(name, args)
                else:
                    result = json.dumps({"error": f"Unknown tool: {name}"})

                _tc_duration = int((time.monotonic() - t0) * 1000)
                _tc_error: str | None = None
                try:
                    _parsed_r = json.loads(result)
                    if isinstance(_parsed_r, dict) and "error" in _parsed_r:
                        _tc_error = str(_parsed_r["error"])
                except Exception:
                    pass
                try:
                    _tc_args = json.loads(args or "{}")
                    if not isinstance(_tc_args, dict):
                        _tc_args = {}
                except Exception:
                    _tc_args = {}
                asyncio.create_task(_record_tool_call(
                    session_id=session_id,
                    client_id=client_id,
                    bot_id=bot.id,
                    tool_name=name,
                    tool_type=_tc_type,
                    server_name=_tc_server,
                    iteration=iteration,
                    arguments=_tc_args,
                    result=result,
                    error=_tc_error,
                    duration_ms=_tc_duration,
                    correlation_id=correlation_id,
                ))

                result_for_llm = result
                try:
                    parsed_tool = json.loads(result_for_llm)
                    if isinstance(parsed_tool, dict) and "client_action" in parsed_tool:
                        embedded_client_actions.append(parsed_tool["client_action"])
                        result_for_llm = parsed_tool.get("message", "Done.")
                except (json.JSONDecodeError, TypeError):
                    pass

                _orig_len = len(result_for_llm)
                _was_summarized = False
                if (
                    _eff_summarize_enabled
                    and name not in _eff_summarize_exclude
                    and (_tc_server is None or _tc_server not in _eff_summarize_exclude)
                    and len(result_for_llm) > _eff_summarize_threshold
                ):
                    _was_summarized = True
                    result_for_llm = await _summarize_tool_result(
                        tool_name=name,
                        content=result_for_llm,
                        model=_eff_summarize_model,
                        max_tokens=_eff_summarize_max_tokens,
                        provider_id=provider_id,
                    )
                    if correlation_id is not None:
                        asyncio.create_task(_record_trace_event(
                            correlation_id=correlation_id,
                            session_id=session_id,
                            bot_id=bot.id,
                            client_id=client_id,
                            event_type="tool_result_summarization",
                            data={
                                "tool_name": name,
                                "original_length": _orig_len,
                                "summarized_length": len(result_for_llm),
                            },
                        ))

                result_preview = result_for_llm[:200] + "..." if len(result_for_llm) > 200 else result_for_llm
                logger.debug("Tool result [%s]: %s", name, result_preview)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_for_llm,
                })

                tool_event: dict[str, Any] = {"type": "tool_result", "tool": name}
                if _was_summarized:
                    tool_event["summarized"] = True
                try:
                    parsed = json.loads(result)
                    if isinstance(parsed, dict) and "error" in parsed:
                        err = parsed["error"]
                        logger.warning("Tool %s returned error: %s", name, err)
                        tool_event["error"] = err
                        _trace("← %s error: %s", name, str(err)[:80])
                    else:
                        _trace("← %s (%d chars)", name, len(result_for_llm))
                except (json.JSONDecodeError, TypeError):
                    _trace("← %s (%d chars)", name, len(result_for_llm))
                if name == "search_memories":
                    if result == "No relevant memories found." or result == "No search query provided.":
                        tool_event["memory_count"] = 0
                    elif result.startswith("Relevant memories:\n\n"):
                        body = result[len("Relevant memories:\n\n"):]
                        tool_event["memory_count"] = 1 + body.count("\n\n---\n\n")
                        if tool_event["memory_count"] > 0:
                            first = body.split("\n\n---\n\n")[0].strip()
                            tool_event["memory_preview"] = (first[:120] + "…") if len(first) > 120 else first
                elif name == "save_memory" and result == "Memory saved.":
                    tool_event["saved"] = True
                yield _event_with_compaction_tag(tool_event, compaction)

        logger.warning("Agent loop hit max iterations (%d)", settings.AGENT_MAX_ITERATIONS)
        messages.append({
            "role": "system",
            "content": "You have used too many tool calls. Please respond to the user now without using any tools.",
        })
        final_kw: dict[str, Any] = {"model": model, "messages": messages}
        if tools_param is not None:
            final_kw["tools"] = tools_param
            final_kw["tool_choice"] = "none"
        from app.services.providers import get_llm_client as _get_client
        response = await _get_client(provider_id).chat.completions.create(**final_kw)
        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if response.usage and correlation_id is not None:
            asyncio.create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="token_usage",
                data={
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                    "iteration": settings.AGENT_MAX_ITERATIONS + 1,
                },
            ))

        text = msg.content or ""
        if native_audio and user_msg_index is not None and not transcript_emitted:
            transcript, text = _extract_transcript(text)
            messages[-1]["content"] = text
            yield _event_with_compaction_tag({"type": "transcript", "text": transcript}, compaction)
            if transcript:
                messages[user_msg_index] = {"role": "user", "content": transcript}
            else:
                messages[user_msg_index] = {"role": "user", "content": "[inaudible]"}
            transcript_emitted = True

        _trace("✓ response (%d chars)", len(text))
        if correlation_id is not None and not compaction:
            asyncio.create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="response",
                data={"text": text[:500], "full_length": len(text)},
            ))
        yield _event_with_compaction_tag({
            "type": "response",
            "text": text,
            "client_actions": (
                _extract_client_actions(messages, turn_start) + embedded_client_actions
            ),
        }, compaction)

    except Exception as exc:
        if correlation_id is not None:
            asyncio.create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="error",
                event_name=type(exc).__name__,
                data={"traceback": traceback.format_exc()[:4000]},
            ))
        raise


async def run_stream(
    messages: list[dict],
    bot: BotConfig,
    user_message: str,
    session_id: uuid.UUID | None = None,
    client_id: str | None = None,
    audio_data: str | None = None,
    audio_format: str | None = None,
    attachments: list[dict] | None = None,
    correlation_id: uuid.UUID | None = None,
    dispatch_type: str | None = None,
    dispatch_config: dict | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Core agent loop as an async generator that yields status events.

    Events:
      {"type": "tool_start", "tool": "<name>"}
      {"type": "tool_result", "tool": "<name>"}
      {"type": "memory_context", "count": <int>}
      {"type": "transcript", "text": "..."}
      {"type": "delegation_post", "bot_id": "...", "text": "...", "reply_in_thread": bool}
      {"type": "response", "text": "...", "client_actions": [...]}

    delegation_post events are emitted just before the response event so that the Slack
    client can post child-bot messages first (giving them an earlier timestamp), then post
    the parent's response as a new message — ensuring correct visual ordering.
    """
    # Track whether this is the outermost run_stream invocation (not a nested call from
    # run_immediate).  Only the outermost instance manages the delegation-post queue;
    # nested calls (child runs inside delegate_to_agent) share the same list so their
    # queued posts bubble up to the outermost emitter.
    from app.agent.context import current_pending_delegation_posts
    _is_outermost_stream = current_pending_delegation_posts.get() is None
    _delegation_posts: list = []
    if _is_outermost_stream:
        current_pending_delegation_posts.set(_delegation_posts)
    else:
        # Reuse the outer list so deeply-nested delegation posts still reach the surface.
        _delegation_posts = current_pending_delegation_posts.get()  # type: ignore[assignment]

    set_agent_context(
        session_id=session_id,
        client_id=client_id,
        bot_id=bot.id,
        correlation_id=correlation_id,
        memory_cross_session=bot.memory.cross_session if bot.memory.enabled else None,
        memory_cross_client=bot.memory.cross_client if bot.memory.enabled else None,
        memory_cross_bot=bot.memory.cross_bot if bot.memory.enabled else None,
        memory_similarity_threshold=bot.memory.similarity_threshold if bot.memory.enabled else None,
        dispatch_type=dispatch_type,
        dispatch_config=dispatch_config,
    )
    native_audio = audio_data is not None
    turn_start = len(messages)
    _inject_chars: dict[str, int] = {}

    # Inject current datetime so the bot can reason about time-based scheduling
    try:
        from zoneinfo import ZoneInfo
        _tz = ZoneInfo(settings.TIMEZONE)
        _now_local = datetime.now(_tz)
        _now_utc = datetime.now(timezone.utc)
        messages.append({
            "role": "system",
            "content": (
                f"Current time: {_now_local.strftime('%Y-%m-%d %H:%M %Z')} "
                f"({_now_utc.strftime('%H:%M UTC')})"
            ),
        })
    except Exception:
        pass  # non-fatal if timezone lookup fails

    # Resolve @mention tags for explicit context/tool injection
    _tagged = await resolve_tags(
        message=user_message,
        bot_skills=bot.skills,
        bot_local_tools=bot.local_tools,
        bot_client_tools=bot.client_tools,
        bot_id=bot.id,
        client_id=client_id,
        session_id=session_id,
    )
    _tagged_skill_names = [t.name for t in _tagged if t.tag_type == "skill"]
    _tagged_knowledge_names = [t.name for t in _tagged if t.tag_type == "knowledge"]
    _tagged_tool_names = [t.name for t in _tagged if t.tag_type == "tool"]
    _tagged_bot_names = [t.name for t in _tagged if t.tag_type == "bot"]
    if _tagged_bot_names:
        set_ephemeral_delegates(_tagged_bot_names)

    if _tagged:
        # Inject tagged skill chunks (bypasses similarity threshold)
        if _tagged_skill_names:
            _tagged_skill_chunks: list[str] = []
            for _sid in _tagged_skill_names:
                _tagged_skill_chunks.extend(await fetch_skill_chunks_by_id(_sid))
            if _tagged_skill_chunks:
                messages.append({
                    "role": "system",
                    "content": "Tagged skill context (explicitly requested):\n\n"
                               + "\n\n---\n\n".join(_tagged_skill_chunks),
                })

        # Inject tagged knowledge docs (bypasses similarity threshold)
        if _tagged_knowledge_names and client_id:
            from app.agent.knowledge import get_knowledge_by_name
            _tagged_know_chunks: list[str] = []
            for _kname in _tagged_knowledge_names:
                _doc = await get_knowledge_by_name(
                    _kname,
                    bot.id,
                    client_id,
                    session_id=session_id,
                    ignore_session_scope=True,
                )
                if _doc:
                    _tagged_know_chunks.append(_doc)
                else:
                    logger.warning("Tagged knowledge %r not found", _kname)
            if _tagged_know_chunks:
                messages.append({
                    "role": "system",
                    "content": "Tagged knowledge (explicitly requested):\n\n"
                               + "\n\n---\n\n".join(_tagged_know_chunks),
                })

        yield {
            "type": "tagged_context",
            "tags": [t.raw for t in _tagged],
            "skills": _tagged_skill_names,
            "knowledge": _tagged_knowledge_names,
            "tools": _tagged_tool_names,
            "bots": _tagged_bot_names,
        }
        if correlation_id is not None:
            asyncio.create_task(_record_trace_event(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot.id,
                client_id=client_id,
                event_type="tagged_context",
                count=len(_tagged),
                data={
                    "tags": [t.raw for t in _tagged],
                    "skills": _tagged_skill_names,
                    "knowledge": _tagged_knowledge_names,
                    "tools": _tagged_tool_names,
                    "bots": _tagged_bot_names,
                },
            ))

    if bot.skills:
        # Inject a skill index so the bot knows which skills are available.
        # The bot uses get_skill(skill_id) to retrieve full content on demand.
        from sqlalchemy import select as _sa_select
        from app.db.engine import async_session as _async_session
        from app.db.models import Skill as _SkillRow
        async with _async_session() as _db:
            _rows = (await _db.execute(
                _sa_select(_SkillRow.id, _SkillRow.name)
                .where(_SkillRow.id.in_(bot.skills))
            )).all()
        if _rows:
            _index_lines = "\n".join(f"- {r.id}: {r.name}" for r in _rows)
            messages.append({
                "role": "system",
                "content": (
                    f"Available skills (use get_skill to retrieve full content):\n{_index_lines}"
                ),
            })
            yield {"type": "skill_index", "count": len(_rows)}
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="skill_index",
                    count=len(_rows),
                    data={"skill_ids": [r.id for r in _rows]},
                ))
    elif bot.rag:
        # Legacy pure-RAG mode: semantic similarity retrieval across all skill docs
        chunks, skill_sim = await retrieve_context(user_message, skill_ids=None)
        if chunks:
            _skill_chars = sum(len(c) for c in chunks)
            _inject_chars["skill_context"] = _skill_chars
            yield {"type": "skill_context", "count": len(chunks), "chars": _skill_chars}
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="skill_context",
                    count=len(chunks),
                    data={"preview": chunks[0][:200], "best_similarity": round(skill_sim, 4), "chars": _skill_chars},
                ))
            context = "\n\n---\n\n".join(chunks)
            messages.append({
                "role": "system",
                "content": f"Relevant context:\n\n{context}",
            })

    # Inject a delegate bot index so the bot knows which agents it can hand off to
    # and their exact IDs (needed for @-tagging and delegate_to_agent tool calls).
    _all_delegate_ids = list(dict.fromkeys(bot.delegate_bots + _tagged_bot_names))
    if _all_delegate_ids:
        from app.agent.bots import get_bot as _get_bot
        _delegate_lines: list[str] = []
        for _did in _all_delegate_ids:
            try:
                _db = _get_bot(_did)
                _desc = (_db.system_prompt or "").strip().splitlines()[0][:120] if _db.system_prompt else ""
                _delegate_lines.append(f"  • {_did} — {_db.name}" + (f": {_desc}" if _desc else ""))
            except Exception:
                _delegate_lines.append(f"  • {_did}")
        if _delegate_lines:
            messages.append({
                "role": "system",
                "content": (
                    "Available sub-agents (delegate via delegate_to_agent or @bot-id in your reply):\n"
                    + "\n".join(_delegate_lines)
                ),
            })
            yield {"type": "delegate_index", "count": len(_delegate_lines)}

    if bot.memory.enabled and session_id and client_id:
        memories, mem_sim = await retrieve_memories(
            query=user_message,
            session_id=session_id,
            client_id=client_id,
            bot_id=bot.id,
            cross_session=bot.memory.cross_session,
            cross_client=bot.memory.cross_client,
            cross_bot=bot.memory.cross_bot,
            similarity_threshold=bot.memory.similarity_threshold,
        )
        if memories:
            _mem_limit = bot.memory_max_inject_chars or settings.MEMORY_MAX_INJECT_CHARS
            memories = [
                m[:_mem_limit] + ("…" if len(m) > _mem_limit else "")
                for m in memories
            ]
            _mem_chars = sum(len(m) for m in memories)
            _inject_chars["memory"] = _mem_chars
            memory_preview = memories[0][:100] + "..." if len(memories[0]) > 100 else memories[0]
            yield {"type": "memory_context", "count": len(memories), "memory_preview": memory_preview, "chars": _mem_chars}
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="memory_injection",
                    count=len(memories),
                    data={"preview": memories[0][:200], "best_similarity": round(mem_sim, 4), "chars": _mem_chars},
                ))
            messages.append({
                "role": "system",
                "content": (
                    "Relevant memories from past conversations (automatically recalled "
                    "based on the user's message; you can use these directly):\n\n"
                    + "\n\n---\n\n".join(memories)
                ),
            })

    if client_id:
        from app.agent.knowledge import get_pinned_knowledge_docs
        pinned_docs, pinned_names = await get_pinned_knowledge_docs(
            bot.id, client_id, session_id=session_id
        )
        if pinned_docs:
            _know_limit = bot.knowledge_max_inject_chars or settings.KNOWLEDGE_MAX_INJECT_CHARS
            pinned_docs = [
                d[:_know_limit] + ("…" if len(d) > _know_limit else "")
                for d in pinned_docs
            ]
            _pinned_chars = sum(len(d) for d in pinned_docs)
            _inject_chars["pinned_knowledge"] = _pinned_chars
            yield {"type": "pinned_knowledge_context", "count": len(pinned_docs), "chars": _pinned_chars}
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="pinned_knowledge_context",
                    count=len(pinned_docs),
                    data={"names": pinned_names, "chars": _pinned_chars},
                ))
            messages.append({
                "role": "system",
                "content": "Pinned knowledge (always available):\n\n" + "\n\n---\n\n".join(pinned_docs),
            })

    if bot.knowledge.enabled and session_id and client_id:
        chunks, know_sim = await retrieve_knowledge(
            query=user_message,
            bot_id=bot.id,
            client_id=client_id,
            fallback_threshold=settings.KNOWLEDGE_SIMILARITY_THRESHOLD,
            session_id=session_id,
        )
        if chunks:
            _know_limit = bot.knowledge_max_inject_chars or settings.KNOWLEDGE_MAX_INJECT_CHARS
            chunks = [
                c[:_know_limit] + ("…" if len(c) > _know_limit else "")
                for c in chunks
            ]
            _know_chars = sum(len(c) for c in chunks)
            _inject_chars["knowledge"] = _know_chars
            knowledge_preview = chunks[0][:100] + "..." if len(chunks[0]) > 100 else chunks[0]
            yield {"type": "knowledge_context", "count": len(chunks), "knowledge_preview": knowledge_preview, "chars": _know_chars}
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="knowledge_context",
                    count=len(chunks),
                    data={"preview": chunks[0][:200], "best_similarity": round(know_sim, 4), "chars": _know_chars},
                ))
            messages.append({"role": "system", "content": "Relevant knowledge:\n\n" + "\n\n---\n\n".join(chunks)})

    # Inject active plans for the current session (always, no bot config flag)
    if session_id:
        from app.db.models import Plan as _Plan, PlanItem as _PlanItem
        from app.db.engine import async_session as _async_session_plans
        from sqlalchemy import select as _sa_select_plans
        async with _async_session_plans() as _pdb:
            _plan_rows = (await _pdb.execute(
                _sa_select_plans(_Plan)
                .where(_Plan.session_id == session_id, _Plan.status == "active")
                .order_by(_Plan.created_at)
            )).scalars().all()
        if _plan_rows:
            _plan_lines: list[str] = []
            for _p in _plan_rows:
                async with _async_session_plans() as _idb:
                    _items = (await _idb.execute(
                        _sa_select_plans(_PlanItem)
                        .where(_PlanItem.plan_id == _p.id)
                        .order_by(_PlanItem.position)
                    )).scalars().all()
                _plan_lines.append(
                    f"## {_p.title}\n" + "\n".join(
                        f"{i.position}. [{i.status}] {i.content}"
                        + (f"\n   notes: {i.notes}" if i.notes else "")
                        for i in _items
                    )
                )
            messages.append({
                "role": "system",
                "content": "Active plans for this session:\n\n" + "\n\n".join(_plan_lines),
            })
            yield {"type": "plans_context", "count": len(_plan_rows)}

    if bot.filesystem_indexes:
        from app.agent.fs_indexer import retrieve_filesystem_context
        # Use the most permissive threshold across all configured indexes (or default)
        fs_threshold = min(
            (cfg.similarity_threshold for cfg in bot.filesystem_indexes if cfg.similarity_threshold is not None),
            default=None,
        )
        fs_chunks, fs_sim = await retrieve_filesystem_context(user_message, bot.id, threshold=fs_threshold)
        if fs_chunks:
            yield {"type": "fs_context", "count": len(fs_chunks)}
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="fs_context",
                    count=len(fs_chunks),
                    data={"preview": fs_chunks[0][:200], "best_similarity": round(fs_sim, 4)},
                ))
            messages.append({
                "role": "system",
                "content": "Relevant code/files from indexed directories:\n\n"
                           + "\n\n---\n\n".join(fs_chunks),
            })

    pre_selected_tools: list[dict[str, Any]] | None = None
    if bot.tool_retrieval and (bot.local_tools or bot.mcp_servers or bot.client_tools):
        by_name = await _all_tool_schemas_by_name(bot)
        if by_name:
            th = (
                bot.tool_similarity_threshold
                if bot.tool_similarity_threshold is not None
                else settings.TOOL_RETRIEVAL_THRESHOLD
            )
            retrieved, tool_sim, tool_candidates = await retrieve_tools(
                user_message,
                bot.local_tools,
                bot.mcp_servers,
                threshold=th,
            )
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="tool_retrieval",
                    count=len(retrieved),
                    data={"best_similarity": tool_sim, "threshold": th,
                          "selected": [t["function"]["name"] for t in retrieved],
                          "top_candidates": tool_candidates},
                ))
            _effective_pinned = list(bot.pinned_tools or []) + _tagged_tool_names + ["get_tool_info"]
            pinned_list = [by_name[n] for n in _effective_pinned if n in by_name]
            # Also support server-level pinning: if a pinned entry is an MCP server name,
            # include all tools from that server.
            _server_pins = {n for n in _effective_pinned if n not in by_name}
            if _server_pins:
                for _tool_name, _schema in by_name.items():
                    if get_mcp_server_for_tool(_tool_name) in _server_pins:
                        pinned_list.append(_schema)
            client_only = get_client_tool_schemas(bot.client_tools)
            merged = _merge_tool_schemas(pinned_list, retrieved, client_only)
            if not merged:
                pre_selected_tools = list(by_name.values())
            else:
                pre_selected_tools = merged

            # Inject compact names index for unretrieved tools
            _retrieved_names = {t["function"]["name"] for t in pre_selected_tools}
            _unretrieved = [
                (n, s["function"].get("description", "")[:80])
                for n, s in by_name.items()
                if n not in _retrieved_names and n != "get_tool_info"
            ]
            if _unretrieved:
                _index_lines = "\n".join(f"  • {n}: {d}" for n, d in _unretrieved)
                messages.append({
                    "role": "system",
                    "content": (
                        "Available tools (not yet loaded — use get_tool_info(tool_name) to get full schema):\n"
                        + _index_lines
                    ),
                })
                yield {"type": "tool_index", "unretrieved_count": len(_unretrieved)}

    if native_audio:
        messages.append({
            "role": "system",
            "content": _AUDIO_TRANSCRIPT_INSTRUCTION,
        })
        user_msg = _build_audio_user_message(audio_data, audio_format)
        messages.append(user_msg)
        user_msg_index = len(messages) - 1
    else:
        user_content = _build_user_message_content(user_message, attachments)
        messages.append({"role": "user", "content": user_content})
        user_msg_index = len(messages) - 1

    if correlation_id is not None and _inject_chars:
        asyncio.create_task(_record_trace_event(
            correlation_id=correlation_id,
            session_id=session_id,
            bot_id=bot.id,
            client_id=client_id,
            event_type="context_injection_summary",
            data={
                "breakdown": _inject_chars,
                "total_chars": sum(_inject_chars.values()),
            },
        ))

    # Only the outermost run_stream buffers the response and emits delegation_post events.
    # Nested calls (child agents inside delegate_to_agent) just pass events through.
    if _is_outermost_stream:
        _last_response: dict | None = None
        async for event in run_agent_tool_loop(
            messages,
            bot,
            session_id=session_id,
            client_id=client_id,
            turn_start=turn_start,
            native_audio=native_audio,
            user_msg_index=user_msg_index,
            pre_selected_tools=pre_selected_tools,
            correlation_id=correlation_id,
        ):
            if event.get("type") == "response":
                _last_response = event
            else:
                yield event
        # Emit child-bot delegation posts BEFORE the parent response so the Slack client
        # can post child messages first (lower Slack timestamp) then repost the parent.
        for _dp in _delegation_posts:
            yield {
                "type": "delegation_post",
                "bot_id": _dp["bot_id"],
                "text": _dp["text"],
                "reply_in_thread": _dp.get("reply_in_thread", False),
            }
        if _last_response is not None:
            yield _last_response
    else:
        async for event in run_agent_tool_loop(
            messages,
            bot,
            session_id=session_id,
            client_id=client_id,
            turn_start=turn_start,
            native_audio=native_audio,
            user_msg_index=user_msg_index,
            pre_selected_tools=pre_selected_tools,
            correlation_id=correlation_id,
        ):
            yield event


async def run(
    messages: list[dict],
    bot: BotConfig,
    user_message: str,
    session_id: uuid.UUID | None = None,
    client_id: str | None = None,
    audio_data: str | None = None,
    audio_format: str | None = None,
    attachments: list[dict] | None = None,
    correlation_id: uuid.UUID | None = None,
    dispatch_type: str | None = None,
    dispatch_config: dict | None = None,
) -> RunResult:
    """Non-streaming wrapper: runs the agent loop and returns the final result."""
    result = RunResult()
    async for event in run_stream(
        messages, bot, user_message,
        session_id=session_id, client_id=client_id,
        audio_data=audio_data, audio_format=audio_format,
        attachments=attachments,
        correlation_id=correlation_id,
        dispatch_type=dispatch_type,
        dispatch_config=dispatch_config,
    ):
        if event["type"] == "response":
            result.response = event["text"]
            result.client_actions = event.get("client_actions", [])
        elif event["type"] == "transcript":
            result.transcript = event["text"]
        elif event["type"] == "delegation_post" and dispatch_type and dispatch_config:
            # Non-streaming context (task worker): deliver child bot's message via appropriate dispatcher.
            from app.services.delegation import delegation_service as _ds
            try:
                await _ds.post_child_response(
                    dispatch_type=dispatch_type,
                    dispatch_config=dispatch_config,
                    text=event.get("text", ""),
                    bot_id=event.get("bot_id") or "",
                    reply_in_thread=event.get("reply_in_thread", False),
                )
            except Exception:
                logger.warning("run(): delegation_post failed for bot %s", event.get("bot_id"))
    return result
