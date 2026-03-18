"""Local tools: search_memories, save_memory — same table as automatic retrieval."""
import copy
import json
import logging
import uuid
from typing import TYPE_CHECKING

from app.agent.context import (
    current_client_id,
    current_bot_id,
    current_memory_cross_client,
    current_memory_cross_bot,
    current_memory_cross_session,
    current_memory_similarity_threshold,
    current_session_id,
)
from app.agent.memory import retrieve_memories, write_memory
from app.config import settings
from app.tools.registry import get_local_tool_schemas, register

if TYPE_CHECKING:
    from app.agent.bots import BotConfig, MemoryConfig

logger = logging.getLogger(__name__)

SEARCH_MEMORIES_DESCRIPTION = (
    "Search long-term memory by semantic similarity. Memories relevant to the user's "
    "message are already injected into your context (see 'Relevant memories from past "
    "conversations' above); you can use those directly when they answer the question. "
    "Only call this tool when you need to search for something else, look up more detail, "
    "or check before saving a new memory."
)

BASE_DESCRIPTION = (
    "Save a fact or observation to long-term memory so it can be recalled in future "
    "conversations. Use for: user preferences, project paths, device names, recurring "
    "problems, or anything that would help you assist the user later. Do not save "
    "routine commands or transient info."
)


@register({
    "type": "function",
    "function": {
        "name": "search_memories",
        "description": SEARCH_MEMORIES_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g. 'user's project paths', 'office devices', 'preferences').",
                },
            },
            "required": ["query"],
        },
    },
})
async def search_memories(query: str) -> str:
    """Search memories; uses session_id, client_id and memory config from agent context."""
    session_id = current_session_id.get()
    client_id = current_client_id.get()
    bot_id = current_bot_id.get()
    if not session_id or not client_id:
        return "Memory search is not available for this conversation (no session context)."
    query = (query or "").strip()
    if not query:
        return "No search query provided."
    cross_session = current_memory_cross_session.get()
    if cross_session is None:
        cross_session = True
    cross_client = current_memory_cross_client.get()
    if cross_client is None:
        cross_client = False
    cross_bot = current_memory_cross_bot.get()
    if cross_bot is None:
        cross_bot = False
    threshold = current_memory_similarity_threshold.get()
    if threshold is None:
        threshold = settings.MEMORY_SIMILARITY_THRESHOLD



    chunks = await retrieve_memories(
        query=query,
        session_id=session_id,
        client_id=client_id,
        bot_id=bot_id,
        cross_session=cross_session,
        cross_client=cross_client,
        cross_bot=cross_bot,
        similarity_threshold=threshold,
    )
    if not chunks:
        return "No relevant memories found."
    return "Relevant memories:\n\n" + "\n\n---\n\n".join(chunks)


@register({
    "type": "function",
    "function": {
        "name": "save_memory",
        "description": BASE_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The fact or observation to store (clear, self-contained sentence or short paragraph).",
                },
            },
            "required": ["content"],
        },
    },
})
async def save_memory(content: str) -> str:
    """Save a memory; uses session_id and client_id from agent context."""
    session_id = current_session_id.get()
    client_id = current_client_id.get()
    bot_id = current_bot_id.get()
    if not session_id or not client_id or not bot_id:
        return "Memory is not available for this conversation (no session context)."
    content = (content or "").strip()
    if not content:
        return "No content provided; nothing was saved."
    ok, err = await write_memory(
        summary_text=content,
        client_id=client_id,
        session_id=session_id,
        bot_id=bot_id,
        message_range_start=None,
        message_range_end=None,
        message_count=None,
    )
    if ok:
        return "Memory saved."
    return f"Failed to save memory: {err}" if err else "Failed to save memory."


# --- Implementations with explicit params (used by the loop; no context vars) ---


async def search_memories_impl(
    query: str,
    session_id: uuid.UUID,
    client_id: str,
    bot_id: str,
    *,
    cross_session: bool = True,
    cross_client: bool = False,
    cross_bot: bool = True,
    similarity_threshold: float | None = None,
) -> str:
    """Search memories; caller passes session_id, client_id, and scope."""
    query = (query or "").strip()
    if not query:
        return "No search query provided."
    threshold = similarity_threshold if similarity_threshold is not None else settings.MEMORY_SIMILARITY_THRESHOLD
    chunks = await retrieve_memories(
        query=query,
        session_id=session_id,
        client_id=client_id,
        bot_id=bot_id,
        cross_session=cross_session,
        cross_client=cross_client,
        cross_bot=cross_bot,
        similarity_threshold=threshold,
    )
    if not chunks:
        return "No relevant memories found."
    return "Relevant memories:\n\n" + "\n\n---\n\n".join(chunks)


async def save_memory_impl(
    content: str,
    session_id: uuid.UUID,
    client_id: str,
    bot_id: str,
) -> str:
    """Save a memory; caller passes session_id and client_id."""
    content = (content or "").strip()
    if not content:
        return "No content provided; nothing was saved."
    ok, err = await write_memory(
        summary_text=content,
        client_id=client_id,
        session_id=session_id,
        bot_id=bot_id,
        message_range_start=None,
        message_range_end=None,
        message_count=None,
    )
    if ok:
        return "Memory saved."
    return f"Failed to save memory: {err}" if err else "Failed to save memory."


async def call_memory_tool(
    name: str,
    arguments_json: str,
    session_id: uuid.UUID,
    client_id: str,
    bot_id: str,
    memory_config: "MemoryConfig",
) -> str:
    """Run a memory tool with session_id, client_id, and config injected by the loop. No context vars."""
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError:
        return "Invalid tool arguments."
    if name == "search_memories":
        return await search_memories_impl(
            args.get("query", ""),
            session_id,
            client_id,
            bot_id,
            cross_session=memory_config.cross_session,
            cross_client=memory_config.cross_client,
            cross_bot=memory_config.cross_bot,
            similarity_threshold=memory_config.similarity_threshold,
        )
    if name == "save_memory":
        return await save_memory_impl(args.get("content", ""), session_id, client_id, bot_id)
    return json.dumps({"error": f"Unknown memory tool: {name}"})


def get_search_memories_tool_schema() -> dict | None:
    """Return search_memories tool schema (no bot-specific overrides)."""
    schemas = get_local_tool_schemas(["search_memories"])
    return schemas[0] if schemas else None


def get_memory_tool_schema(bot: "BotConfig") -> dict | None:
    """Return save_memory tool schema; if bot has memory.prompt, append it to the description."""
    schemas = get_local_tool_schemas(["save_memory"])
    if not schemas:
        return None
    schema = copy.deepcopy(schemas[0])
    if bot.memory.prompt:
        schema["function"]["description"] = (
            schema["function"]["description"].rstrip() + "\n\n" + bot.memory.prompt.strip()
        )
    return schema


def get_memory_tool_schemas(bot: "BotConfig") -> list[dict]:
    """Return [search_memories, save_memory] schemas when memory is enabled (search first)."""
    out: list[dict] = []
    search_schema = get_search_memories_tool_schema()
    if search_schema:
        out.append(search_schema)
    save_schema = get_memory_tool_schema(bot)
    if save_schema:
        out.append(save_schema)
    return out
