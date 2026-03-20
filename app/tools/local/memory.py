"""Local tools: search_memories, save_memory, purge_memory, merge_memories."""
import copy
import json
import logging
import uuid
from typing import TYPE_CHECKING

from app.agent.context import (
    current_client_id,
    current_bot_id,
    current_correlation_id,
    current_memory_cross_client,
    current_memory_cross_bot,
    current_memory_cross_session,
    current_memory_similarity_threshold,
    current_session_id,
)
from app.agent.memory import (
    delete_memory_scoped,
    format_memory_search_hit,
    merge_memories_scoped,
    retrieve_memory_matches,
    write_memory,
)
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
    "or check before saving a new memory. Each result starts with id: <uuid> — use that "
    "with purge_memory or merge_memories."
)

BASE_DESCRIPTION = (
    "Save a fact or observation to long-term memory so it can be recalled in future "
    "conversations. Use for: user preferences, project paths, device names, recurring "
    "problems, or anything that would help you assist the user later. Do not save "
    "routine commands or transient info."
)

PURGE_MEMORY_DESCRIPTION = (
    "Delete one memory row by id (use the id from search_memories results). "
    "Only memories visible under this bot's memory scope can be removed."
)

MERGE_MEMORIES_DESCRIPTION = (
    "Merge two or more memories into one: deletes the listed rows and saves a single new "
    "memory (re-embedded). Pass merged_content for a concise combined fact; omit it to "
    "concatenate the originals with blank lines."
)


def _parse_uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value).strip())
    except (ValueError, AttributeError, TypeError):
        return None


def _parse_memory_id_list(raw: object) -> list[uuid.UUID] | None:
    if not isinstance(raw, list) or len(raw) < 2:
        return None
    out: list[uuid.UUID] = []
    for item in raw:
        uid = _parse_uuid(item)
        if uid is None:
            return None
        out.append(uid)
    return out

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

    matches, _ = await retrieve_memory_matches(
        query=query,
        session_id=session_id,
        client_id=client_id,
        bot_id=bot_id,
        cross_session=cross_session,
        cross_client=cross_client,
        cross_bot=cross_bot,
        similarity_threshold=threshold,
    )
    if not matches:
        return "No relevant memories found."
    lines = [format_memory_search_hit(mid, content, created_at) for mid, content, created_at, _s in matches]
    return "Relevant memories:\n\n" + "\n\n---\n\n".join(lines)


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
    correlation_id = current_correlation_id.get()
    ok, err = await write_memory(
        summary_text=content,
        client_id=client_id,
        session_id=session_id,
        bot_id=bot_id,
        message_range_start=None,
        message_range_end=None,
        message_count=None,
        correlation_id=correlation_id,
    )
    if ok:
        return "Memory saved."
    return f"Failed to save memory: {err}" if err else "Failed to save memory."


@register({
    "type": "function",
    "function": {
        "name": "purge_memory",
        "description": PURGE_MEMORY_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "UUID of the memory to delete (from search_memories).",
                },
            },
            "required": ["memory_id"],
        },
    },
})
async def purge_memory(memory_id: str) -> str:
    session_id = current_session_id.get()
    client_id = current_client_id.get()
    bot_id = current_bot_id.get()
    if not session_id or not client_id or not bot_id:
        return "Memory is not available for this conversation (no session context)."
    from app.agent.bots import get_bot
    bot = get_bot(bot_id)
    return await purge_memory_impl(memory_id, session_id, client_id, bot_id, bot.memory)


@register({
    "type": "function",
    "function": {
        "name": "merge_memories",
        "description": MERGE_MEMORIES_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "memory_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Two or more memory UUIDs to merge (order preserved when concatenating).",
                },
                "merged_content": {
                    "type": "string",
                    "description": "Optional. Final text for the single new memory; omit to join originals.",
                },
            },
            "required": ["memory_ids"],
        },
    },
})
async def merge_memories(memory_ids: list, merged_content: str | None = None) -> str:
    session_id = current_session_id.get()
    client_id = current_client_id.get()
    bot_id = current_bot_id.get()
    if not session_id or not client_id or not bot_id:
        return "Memory is not available for this conversation (no session context)."
    from app.agent.bots import get_bot
    bot = get_bot(bot_id)
    correlation_id = current_correlation_id.get()
    return await merge_memories_impl(
        memory_ids, merged_content, session_id, client_id, bot_id, bot.memory, correlation_id
    )


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
    matches, _ = await retrieve_memory_matches(
        query=query,
        session_id=session_id,
        client_id=client_id,
        bot_id=bot_id,
        cross_session=cross_session,
        cross_client=cross_client,
        cross_bot=cross_bot,
        similarity_threshold=threshold,
    )
    if not matches:
        return "No relevant memories found."
    lines = [format_memory_search_hit(mid, content, created_at) for mid, content, created_at, _s in matches]
    return "Relevant memories:\n\n" + "\n\n---\n\n".join(lines)


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


async def purge_memory_impl(
    memory_id: str,
    session_id: uuid.UUID,
    client_id: str,
    bot_id: str,
    memory_config: "MemoryConfig",
) -> str:
    mid = _parse_uuid(memory_id)
    if mid is None:
        return "Invalid memory_id (expected UUID)."
    ok, err = await delete_memory_scoped(
        mid,
        session_id,
        client_id,
        bot_id,
        cross_session=memory_config.cross_session,
        cross_client=memory_config.cross_client,
        cross_bot=memory_config.cross_bot,
    )
    if ok:
        return "Memory deleted."
    return err or "Failed to delete memory."


async def merge_memories_impl(
    memory_ids: object,
    merged_content: str | None,
    session_id: uuid.UUID,
    client_id: str,
    bot_id: str,
    memory_config: "MemoryConfig",
    correlation_id: uuid.UUID | None = None,
) -> str:
    parsed = _parse_memory_id_list(memory_ids)
    if parsed is None:
        return "memory_ids must be an array of at least two UUID strings."
    ok, err, new_id = await merge_memories_scoped(
        parsed,
        merged_content,
        session_id,
        client_id,
        bot_id,
        cross_session=memory_config.cross_session,
        cross_client=memory_config.cross_client,
        cross_bot=memory_config.cross_bot,
        correlation_id=correlation_id,
    )
    if ok and new_id:
        return f"Memories merged into new id: {new_id}."
    return err or "Failed to merge memories."


async def call_memory_tool(
    name: str,
    arguments_json: str,
    session_id: uuid.UUID,
    client_id: str,
    bot_id: str,
    memory_config: "MemoryConfig",
    *,
    correlation_id: uuid.UUID | None = None,
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
    if name == "purge_memory":
        return await purge_memory_impl(
            str(args.get("memory_id", "")),
            session_id,
            client_id,
            bot_id,
            memory_config,
        )
    if name == "merge_memories":
        return await merge_memories_impl(
            args.get("memory_ids"),
            args.get("merged_content"),
            session_id,
            client_id,
            bot_id,
            memory_config,
            correlation_id,
        )
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
    """Memory tool schemas (search first, then save / purge / merge)."""
    out: list[dict] = []
    search_schema = get_search_memories_tool_schema()
    if search_schema:
        out.append(search_schema)
    save_schema = get_memory_tool_schema(bot)
    if save_schema:
        out.append(save_schema)
    for extra in get_local_tool_schemas(["purge_memory", "merge_memories"]):
        out.append(extra)
    return out
