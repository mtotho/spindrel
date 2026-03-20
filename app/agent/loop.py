import asyncio
import json
import logging
import re
import time
import traceback
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI

from app.agent.bots import BotConfig
from app.agent.context import set_agent_context
from app.agent.memory import retrieve_memories
from app.agent.knowledge import retrieve_knowledge
from app.agent.pending import CLIENT_TOOL_TIMEOUT, create_pending
from app.agent.rag import retrieve_context
from app.agent.tools import retrieve_tools
from app.config import settings
from app.db.engine import async_session
from app.db.models import ToolCall, TraceEvent
from app.tools.client_tools import get_client_tool_schemas, is_client_tool
from app.tools.mcp import call_mcp_tool, fetch_mcp_tools, is_mcp_tool
from app.tools.local.memory import call_memory_tool
from app.tools.registry import call_local_tool, get_local_tool_schemas, is_local_tool
from app.tools.local.persona import call_persona_tool
from app.tools.local.knowledge import call_knowledge_tool

logger = logging.getLogger(__name__)


async def _record_tool_call(
    *,
    session_id: uuid.UUID | None,
    client_id: str | None,
    bot_id: str | None,
    tool_name: str,
    tool_type: str,
    server_name: str | None,
    iteration: int,
    arguments: dict,
    result: str | None,
    error: str | None,
    duration_ms: int,
    correlation_id: uuid.UUID | None = None,
) -> None:
    """Fire-and-forget: write a ToolCall row to the DB."""
    try:
        async with async_session() as db:
            db.add(ToolCall(
                session_id=session_id,
                client_id=client_id,
                bot_id=bot_id,
                tool_name=tool_name,
                tool_type=tool_type,
                server_name=server_name,
                iteration=iteration,
                arguments=arguments,
                result=result[:4000] if result else None,
                error=error,
                duration_ms=duration_ms,
                correlation_id=correlation_id,
                created_at=datetime.now(timezone.utc),
            ))
            await db.commit()
    except Exception:
        logger.exception("Failed to record tool call for %s", tool_name)


async def _record_trace_event(
    *,
    correlation_id: uuid.UUID,
    session_id: uuid.UUID | None,
    bot_id: str | None,
    client_id: str | None,
    event_type: str,
    event_name: str | None = None,
    count: int | None = None,
    data: dict | None = None,
    duration_ms: int | None = None,
) -> None:
    """Fire-and-forget: write a TraceEvent row to the DB."""
    try:
        async with async_session() as db:
            db.add(TraceEvent(
                correlation_id=correlation_id,
                session_id=session_id,
                bot_id=bot_id,
                client_id=client_id,
                event_type=event_type,
                event_name=event_name,
                count=count,
                data=data,
                duration_ms=duration_ms,
                created_at=datetime.now(timezone.utc),
            ))
            await db.commit()
    except Exception:
        logger.exception("Failed to record trace event %s", event_type)


def _trace(msg: str, *args: Any) -> None:
    """Log a single-line agent trace when AGENT_TRACE is enabled (no JSON)."""
    if settings.AGENT_TRACE:
        logger.info("[agent] " + msg, *args)

_client = AsyncOpenAI(
    base_url=settings.LITELLM_BASE_URL,
    api_key=settings.LITELLM_API_KEY,
    timeout=60.0,
)

_TRANSCRIPT_RE = re.compile(r"\[transcript\](.*?)\[/transcript\]", re.DOTALL)

_AUDIO_TRANSCRIPT_INSTRUCTION = (
    "The user's message includes audio input. Before your response, include an exact "
    "transcription of what the user said in [transcript]...[/transcript] tags. "
    "Place the transcript on its own line before your actual reply. Example:\n"
    "[transcript]Hello, how are you?[/transcript]\n"
    "I'm doing well! How can I help?"
)


def _build_user_message_content(text: str, attachments: list[dict] | None) -> str | list[dict]:
    """OpenAI-style multimodal user content for LiteLLM. `attachments` items: type image, content (base64), mime_type."""
    if not attachments:
        return text
    parts: list[dict] = [{"type": "text", "text": text or "(no text)"}]
    for att in attachments:
        if att.get("type") != "image":
            continue
        mime = att.get("mime_type") or "image/jpeg"
        b64 = att.get("content") or ""
        if not b64:
            continue
        parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        })
    return parts


def _build_audio_user_message(audio_data: str, audio_format: str | None) -> dict:
    """Construct a multimodal user message with an audio content part."""
    fmt = audio_format or "m4a"
    return {
        "role": "user",
        "content": [
            {
                "type": "input_audio",
                "input_audio": {"data": audio_data, "format": fmt},
            },
        ],
    }


def _extract_transcript(text: str) -> tuple[str, str]:
    """Parse [transcript]...[/transcript] from model response.

    Returns (transcript, clean_response). If no tags found, transcript is empty
    and clean_response is the original text.
    """
    match = _TRANSCRIPT_RE.search(text)
    if not match:
        return "", text

    transcript = match.group(1).strip()
    clean = text[:match.start()] + text[match.end():]
    return transcript, clean.strip()


@dataclass
class RunResult:
    response: str = ""
    transcript: str = ""
    client_actions: list[dict] = field(default_factory=list)


def _extract_client_actions(messages: list[dict], from_index: int) -> list[dict]:
    """Scan messages added during this turn for client_action tool calls."""
    actions = []
    for msg in messages[from_index:]:
        if msg.get("role") != "assistant" or not msg.get("tool_calls"):
            continue
        for tc in msg["tool_calls"]:
            if tc.get("function", {}).get("name") == "client_action":
                try:
                    args = json.loads(tc["function"]["arguments"])
                    actions.append(args)
                except (json.JSONDecodeError, KeyError):
                    pass
    return actions


def _event_with_compaction_tag(event: dict[str, Any], compaction: bool) -> dict[str, Any]:
    if compaction:
        return {**event, "compaction": True}
    return event


def _merge_tool_schemas(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for group in groups:
        for t in group:
            fn = t.get("function") or {}
            name = fn.get("name")
            if not name or name in seen:
                continue
            seen.add(name)
            out.append(t)
    return out


async def _all_tool_schemas_by_name(bot: BotConfig) -> dict[str, dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    for t in get_local_tool_schemas(bot.local_tools):
        by_name[t["function"]["name"]] = t
    for t in await fetch_mcp_tools(bot.mcp_servers):
        by_name[t["function"]["name"]] = t
    for t in get_client_tool_schemas(bot.client_tools):
        by_name[t["function"]["name"]] = t
    return by_name


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
    if pre_selected_tools is not None:
        all_tools = list(pre_selected_tools)
    else:
        local_schemas = get_local_tool_schemas(bot.local_tools)
        mcp_schemas = await fetch_mcp_tools(bot.mcp_servers)
        client_schemas = get_client_tool_schemas(bot.client_tools)
        all_tools = local_schemas + mcp_schemas + client_schemas
    tools_param = all_tools if all_tools else None
    tool_choice = "auto" if tools_param else None

    logger.debug("Tools available: %s", [t["function"]["name"] for t in all_tools] if all_tools else "(none)")

    transcript_emitted = False
    embedded_client_actions: list[dict] = []

    try:
        for iteration in range(settings.AGENT_MAX_ITERATIONS):
            logger.debug("--- Iteration %d ---", iteration + 1)
            logger.debug("Calling LLM (%s) with %d messages", model, len(messages))

            response = await _client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools_param,
                tool_choice=tool_choice,
            )
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
                        retry = await _client.chat.completions.create(
                            model=model,
                            messages=messages,
                        )
                        text = retry.choices[0].message.content or ""
                        messages.append(retry.choices[0].message.model_dump(exclude_none=True))
                    except Exception as exc:
                        logger.error("Forced-response retry failed: %s", exc)
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
                    if name in ("search_memories", "save_memory") and session_id and client_id:
                        result = await call_memory_tool(
                            name, args or "{}", session_id, client_id, bot.id, bot.memory
                        )
                    elif name == "update_persona":
                        result = await call_persona_tool(name, args or "{}", bot.id)
                    elif name in ("upsert_knowledge", "get_knowledge", "search_knowledge", "list_knowledge_bases") and client_id:
                        result = await call_knowledge_tool(
                            name, args or "{}", bot.id, client_id,
                            bot.knowledge.cross_bot, bot.knowledge.cross_client, bot.knowledge.similarity_threshold,
                        )
                    else:
                        result = await call_local_tool(name, args)
                elif is_mcp_tool(name):
                    _tc_type = "mcp"
                    from app.tools.mcp import get_mcp_server_for_tool
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

                result_preview = result_for_llm[:200] + "..." if len(result_for_llm) > 200 else result_for_llm
                logger.debug("Tool result [%s]: %s", name, result_preview)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_for_llm,
                })

                tool_event: dict[str, Any] = {"type": "tool_result", "tool": name}
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
        response = await _client.chat.completions.create(
            model=model,
            messages=messages,
        )
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
) -> AsyncGenerator[dict[str, Any], None]:
    """Core agent loop as an async generator that yields status events.

    Events:
      {"type": "tool_start", "tool": "<name>"}
      {"type": "tool_result", "tool": "<name>"}
      {"type": "memory_context", "count": <int>}
      {"type": "transcript", "text": "..."}
      {"type": "response", "text": "...", "client_actions": [...]}
    """
    set_agent_context(
        session_id=session_id,
        client_id=client_id,
        bot_id=bot.id,
        correlation_id=correlation_id,
        memory_cross_session=bot.memory.cross_session if bot.memory.enabled else None,
        memory_cross_client=bot.memory.cross_client if bot.memory.enabled else None,
        memory_cross_bot=bot.memory.cross_bot if bot.memory.enabled else None,
        memory_similarity_threshold=bot.memory.similarity_threshold if bot.memory.enabled else None,
    )
    native_audio = audio_data is not None
    turn_start = len(messages)

    skill_ids = bot.skills if bot.skills else None
    if bot.skills or bot.rag:
        chunks, skill_sim = await retrieve_context(user_message, skill_ids=skill_ids)
        if chunks:
            yield {"type": "skill_context", "count": len(chunks)}
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="skill_context",
                    count=len(chunks),
                    data={"preview": chunks[0][:200], "best_similarity": round(skill_sim, 4)},
                ))
            context = "\n\n---\n\n".join(chunks)
            messages.append({
                "role": "system",
                "content": f"Relevant context:\n\n{context}",
            })

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
            memory_preview = memories[0][:100] + "..." if len(memories[0]) > 100 else memories[0]
            yield {"type": "memory_context", "count": len(memories), "memory_preview": memory_preview}
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="memory_injection",
                    count=len(memories),
                    data={"preview": memories[0][:200], "best_similarity": round(mem_sim, 4)},
                ))
            messages.append({
                "role": "system",
                "content": (
                    "Relevant memories from past conversations (automatically recalled "
                    "based on the user's message; you can use these directly):\n\n"
                    + "\n\n---\n\n".join(memories)
                ),
            })

    if bot.knowledge.enabled and session_id and client_id:
        chunks, know_sim = await retrieve_knowledge(
            query=user_message,
            bot_id=bot.id,
            client_id=client_id,
            cross_bot=bot.knowledge.cross_bot,
            cross_client=bot.knowledge.cross_client,
            similarity_threshold=bot.knowledge.similarity_threshold,
        )
        if chunks:
            knowledge_preview = chunks[0][:100] + "..." if len(chunks[0]) > 100 else chunks[0]
            yield {"type": "knowledge_context", "count": len(chunks), "knowledge_preview": knowledge_preview}
            if correlation_id is not None:
                asyncio.create_task(_record_trace_event(
                    correlation_id=correlation_id,
                    session_id=session_id,
                    bot_id=bot.id,
                    client_id=client_id,
                    event_type="knowledge_context",
                    count=len(chunks),
                    data={"preview": chunks[0][:200], "best_similarity": round(know_sim, 4)},
                ))
            messages.append({"role": "system", "content": "Relevant knowledge:\n\n" + "\n\n---\n\n".join(chunks)})

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
            pinned_list = [by_name[n] for n in (bot.pinned_tools or []) if n in by_name]
            client_only = get_client_tool_schemas(bot.client_tools)
            merged = _merge_tool_schemas(pinned_list, retrieved, client_only)
            if not merged:
                pre_selected_tools = list(by_name.values())
            else:
                pre_selected_tools = merged

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
) -> RunResult:
    """Non-streaming wrapper: runs the agent loop and returns the final result."""
    result = RunResult()
    async for event in run_stream(
        messages, bot, user_message,
        session_id=session_id, client_id=client_id,
        audio_data=audio_data, audio_format=audio_format,
        attachments=attachments,
        correlation_id=correlation_id,
    ):
        if event["type"] == "response":
            result.response = event["text"]
            result.client_actions = event.get("client_actions", [])
        elif event["type"] == "transcript":
            result.transcript = event["text"]
    return result
