import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from app.agent.bots import BotConfig
from app.agent.pending import CLIENT_TOOL_TIMEOUT, create_pending
from app.agent.rag import retrieve_context
from app.config import settings
from app.tools.client_tools import get_client_tool_schemas, is_client_tool
from app.tools.mcp import call_mcp_tool, fetch_mcp_tools
from app.tools.registry import call_local_tool, get_local_tool_schemas, is_local_tool

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(
    base_url=settings.LITELLM_BASE_URL,
    api_key=settings.LITELLM_API_KEY,
    timeout=60.0,
)


@dataclass
class RunResult:
    response: str = ""
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
    messages: list[dict], bot: BotConfig, user_message: str
) -> AsyncGenerator[dict[str, Any], None]:
    """Core agent loop as an async generator that yields status events.

    Events:
      {"type": "tool_start", "tool": "<name>"}
      {"type": "tool_result", "tool": "<name>"}
      {"type": "response", "text": "...", "client_actions": [...]}
    """
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

    messages.append({"role": "user", "content": user_message})

    local_schemas = get_local_tool_schemas(bot.local_tools)
    mcp_schemas = await fetch_mcp_tools(bot.mcp_servers)
    client_schemas = get_client_tool_schemas(bot.client_tools)
    all_tools = local_schemas + mcp_schemas + client_schemas
    tools_param = all_tools if all_tools else None
    tool_choice = "auto" if tools_param else None

    tool_names = [t["function"]["name"] for t in all_tools] if all_tools else []
    logger.debug("Tools available: %s", tool_names or "(none)")

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
            logger.info("Final response (%d chars): %r", len(text), text[:120])
            yield {
                "type": "response",
                "text": text,
                "client_actions": _extract_client_actions(messages, turn_start),
            }
            return

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
                result = await call_local_tool(name, args)
            elif any(name.startswith(f"{s}_") for s in bot.mcp_servers):
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
    yield {
        "type": "response",
        "text": msg.content or "",
        "client_actions": _extract_client_actions(messages, turn_start),
    }


async def run(messages: list[dict], bot: BotConfig, user_message: str) -> RunResult:
    """Non-streaming wrapper: runs the agent loop and returns the final result."""
    result = RunResult()
    async for event in run_stream(messages, bot, user_message):
        if event["type"] == "response":
            result.response = event["text"]
            result.client_actions = event.get("client_actions", [])
    return result
