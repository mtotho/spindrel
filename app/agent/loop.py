import json
import logging

from openai import AsyncOpenAI

from app.agent.bots import BotConfig
from app.agent.rag import retrieve_context
from app.config import settings
from app.tools.mcp import call_mcp_tool, fetch_mcp_tools
from app.tools.registry import call_local_tool, get_local_tool_schemas, is_local_tool

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(
    base_url=settings.LITELLM_BASE_URL,
    api_key=settings.LITELLM_API_KEY,
    timeout=60.0,
)


async def run(messages: list[dict], bot: BotConfig, user_message: str) -> str:
    if bot.rag:
        chunks = await retrieve_context(user_message)
        if chunks:
            context = "\n\n---\n\n".join(chunks)
            messages.append({
                "role": "system",
                "content": f"Relevant context:\n\n{context}",
            })

    messages.append({"role": "user", "content": user_message})

    local_schemas = get_local_tool_schemas(bot.local_tools)
    mcp_schemas = await fetch_mcp_tools(bot.mcp_servers)
    all_tools = local_schemas + mcp_schemas
    tools_param = all_tools if all_tools else None
    tool_choice = "auto" if tools_param else None

    for iteration in range(settings.AGENT_MAX_ITERATIONS):
        response = await _client.chat.completions.create(
            model=bot.model,
            messages=messages,
            tools=tools_param,
            tool_choice=tool_choice,
        )
        msg = response.choices[0].message
        msg_dict = msg.model_dump(exclude_none=True)
        messages.append(msg_dict)

        if not msg.tool_calls:
            return msg.content or ""

        for tc in msg.tool_calls:
            name = tc.function.name
            args = tc.function.arguments

            if is_local_tool(name):
                result = await call_local_tool(name, args)
            elif any(
                name.startswith(f"{s}_") for s in bot.mcp_servers
            ):
                result = await call_mcp_tool(name, args)
            else:
                result = json.dumps({"error": f"Unknown tool: {name}"})

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

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
    return msg.content or ""
