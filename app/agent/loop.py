import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from app.agent.bots import BotConfig
from app.agent.memory import retrieve_memories
from app.agent.pending import CLIENT_TOOL_TIMEOUT, create_pending
from app.agent.rag import retrieve_context
from app.config import settings
from app.tools.client_tools import get_client_tool_schemas, is_client_tool
from app.tools.mcp import call_mcp_tool, fetch_mcp_tools, is_mcp_tool
from app.tools.local.memory import call_memory_tool
from app.tools.registry import call_local_tool, get_local_tool_schemas, is_local_tool

logger = logging.getLogger(__name__)

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


async def run_stream(
    messages: list[dict],
    bot: BotConfig,
    user_message: str,
    session_id: uuid.UUID | None = None,
    client_id: str | None = None,
    audio_data: str | None = None,
    audio_format: str | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Core agent loop as an async generator that yields status events.

    Events:
      {"type": "tool_start", "tool": "<name>"}
      {"type": "tool_result", "tool": "<name>"}
      {"type": "memory_context", "count": <int>}
      {"type": "transcript", "text": "..."}
      {"type": "response", "text": "...", "client_actions": [...]}
    """
    native_audio = audio_data is not None
    turn_start = len(messages)

    skill_ids = bot.skills if bot.skills else None
    if bot.skills or bot.rag:
        chunks = await retrieve_context(user_message, skill_ids=skill_ids)
        if chunks:
            yield {"type": "skill_context", "count": len(chunks)}
            context = "\n\n---\n\n".join(chunks)
            messages.append({
                "role": "system",
                "content": f"Relevant context:\n\n{context}",
            })

    if bot.memory.enabled and session_id and client_id:
        memories = await retrieve_memories(
            query=user_message,
            session_id=session_id,
            client_id=client_id,
            cross_session=bot.memory.cross_session,
            cross_client=bot.memory.cross_client,
            similarity_threshold=bot.memory.similarity_threshold,
        )
        if memories:
            yield {"type": "memory_context", "count": len(memories)}
            messages.append({
                "role": "system",
                "content": (
                    "Relevant memories from past conversations (automatically recalled "
                    "based on the user's message; you can use these directly):\n\n"
                    + "\n\n---\n\n".join(memories)
                ),
            })

    if native_audio:
        messages.append({
            "role": "system",
            "content": _AUDIO_TRANSCRIPT_INSTRUCTION,
        })
        user_msg = _build_audio_user_message(audio_data, audio_format)
        messages.append(user_msg)
        user_msg_index = len(messages) - 1
    else:
        messages.append({"role": "user", "content": user_message})
        user_msg_index = len(messages) - 1

    local_schemas = get_local_tool_schemas(bot.local_tools)
    mcp_schemas = await fetch_mcp_tools(bot.mcp_servers)
    client_schemas = get_client_tool_schemas(bot.client_tools)
    all_tools = local_schemas + mcp_schemas + client_schemas
    tools_param = all_tools if all_tools else None
    tool_choice = "auto" if tools_param else None

    logger.debug("Tools available: %s", [t["function"]["name"] for t in all_tools] if all_tools else "(none)")

    transcript_emitted = False

    for iteration in range(settings.AGENT_MAX_ITERATIONS):
        logger.debug("--- Iteration %d ---", iteration + 1)
        logger.debug("Calling LLM (%s) with %d messages", bot.model, len(messages))

        response = await _client.chat.completions.create(
            model=bot.model,
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

        if not msg.tool_calls:
            text = msg.content or ""

            if native_audio and not transcript_emitted:
                transcript, text = _extract_transcript(text)
                # Update the stored assistant message to strip transcript tags
                messages[-1]["content"] = text
                yield {"type": "transcript", "text": transcript}
                if transcript:
                    logger.info("Audio transcript: %r", transcript[:100])
                    messages[user_msg_index] = {"role": "user", "content": transcript}
                else:
                    logger.warning("Native audio response contained no transcript tags")
                    messages[user_msg_index] = {"role": "user", "content": "[inaudible]"}
                transcript_emitted = True

            logger.info("Final response (%d chars): %r", len(text), text[:120])
            yield {
                "type": "response",
                "text": text,
                "client_actions": _extract_client_actions(messages, turn_start),
            }
            return

        # If native audio and first iteration with tool calls, try to extract
        # transcript from any content the model returned alongside tool calls
        if native_audio and not transcript_emitted and msg.content:
            transcript, remaining = _extract_transcript(msg.content)
            if transcript:
                logger.info("Audio transcript (from tool-call response): %r", transcript[:100])
                yield {"type": "transcript", "text": transcript}
                messages[user_msg_index] = {"role": "user", "content": transcript}
                transcript_emitted = True

        logger.info("LLM requested %d tool call(s)", len(msg.tool_calls))

        for tc in msg.tool_calls:
            name = tc.function.name
            args = tc.function.arguments
            logger.info("Tool call: %s(%s)", name, args)

            yield {"type": "tool_start", "tool": name}

            if is_client_tool(name):
                request_id = str(uuid.uuid4())
                try:
                    tool_args = json.loads(args) if args else {}
                except (json.JSONDecodeError, TypeError):
                    tool_args = {}
                yield {
                    "type": "tool_request",
                    "request_id": request_id,
                    "tool": name,
                    "arguments": tool_args,
                }
                future = create_pending(request_id)
                try:
                    result = await asyncio.wait_for(future, timeout=CLIENT_TOOL_TIMEOUT)
                except asyncio.TimeoutError:
                    logger.warning("Client tool %s timed out (request %s)", name, request_id)
                    result = json.dumps({"error": "Client did not respond in time"})
            elif is_local_tool(name):
                # Memory tools get session_id, client_id, and config from the loop (no context vars).
                if name in ("search_memories", "save_memory") and session_id and client_id:
                    result = await call_memory_tool(
                        name, args or "{}", session_id, client_id, bot.memory
                    )
                else:
                    result = await call_local_tool(name, args)
            elif is_mcp_tool(name):
                result = await call_mcp_tool(name, args)
            else:
                result = json.dumps({"error": f"Unknown tool: {name}"})

            result_preview = result[:200] + "..." if len(result) > 200 else result
            logger.debug("Tool result [%s]: %s", name, result_preview)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

            tool_event: dict[str, Any] = {"type": "tool_result", "tool": name}
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "error" in parsed:
                    logger.warning("Tool %s returned error: %s", name, parsed["error"])
                    tool_event["error"] = parsed["error"]
            except (json.JSONDecodeError, TypeError):
                pass
            # Extra fields for CLI when using memory tools
            if name == "search_memories":
                if result == "No relevant memories found." or result == "No search query provided.":
                    tool_event["memory_count"] = 0
                elif result.startswith("Relevant memories:\n\n"):
                    body = result[len("Relevant memories:\n\n") :]
                    tool_event["memory_count"] = 1 + body.count("\n\n---\n\n")
                    if tool_event["memory_count"] > 0:
                        first = body.split("\n\n---\n\n")[0].strip()
                        tool_event["memory_preview"] = (first[:120] + "…") if len(first) > 120 else first
            elif name == "save_memory" and result == "Memory saved.":
                tool_event["saved"] = True
            yield tool_event

    logger.warning("Agent loop hit max iterations (%d)", settings.AGENT_MAX_ITERATIONS)
    messages.append({
        "role": "system",
        "content": "You have used too many tool calls. Please respond to the user now without using any tools.",
    })
    response = await _client.chat.completions.create(
        model=bot.model,
        messages=messages,
    )
    msg = response.choices[0].message
    messages.append(msg.model_dump(exclude_none=True))

    text = msg.content or ""
    if native_audio and not transcript_emitted:
        transcript, text = _extract_transcript(text)
        messages[-1]["content"] = text
        yield {"type": "transcript", "text": transcript}
        if transcript:
            messages[user_msg_index] = {"role": "user", "content": transcript}
        else:
            messages[user_msg_index] = {"role": "user", "content": "[inaudible]"}

    yield {
        "type": "response",
        "text": text,
        "client_actions": _extract_client_actions(messages, turn_start),
    }


async def run(
    messages: list[dict],
    bot: BotConfig,
    user_message: str,
    session_id: uuid.UUID | None = None,
    client_id: str | None = None,
    audio_data: str | None = None,
    audio_format: str | None = None,
) -> RunResult:
    """Non-streaming wrapper: runs the agent loop and returns the final result."""
    result = RunResult()
    async for event in run_stream(
        messages, bot, user_message,
        session_id=session_id, client_id=client_id,
        audio_data=audio_data, audio_format=audio_format,
    ):
        if event["type"] == "response":
            result.response = event["text"]
            result.client_actions = event.get("client_actions", [])
        elif event["type"] == "transcript":
            result.transcript = event["text"]
    return result
