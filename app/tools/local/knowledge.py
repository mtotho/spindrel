import json
import logging

from app.agent.knowledge import (
    append_to_knowledge,
    create_knowledge_pin,
    delete_knowledge_pin,
    get_knowledge_by_name,
    list_knowledge_bases,
    retrieve_knowledge,
    upsert_knowledge,
)
from app.tools.registry import register

logger = logging.getLogger(__name__)

UPSERT_KNOWLEDGE_DESCRIPTION = (
    "Create or update a knowledge document about a topic, project, or system. "
    "Use for structured, multi-faceted information that will grow over time — "
    "e.g. 'project_xyz_architecture', 'home_network_layout', 'bayada_cicd_setup'. "
    "Unlike memories (single facts), knowledge docs are living documents you update "
    "as understanding deepens. Use scope to control sharing: 'channel' (default, any bot in this channel), "
    "'global' (all bots everywhere), 'bot' (this bot across all channels), 'private' (this bot+channel only)."
)

GET_KNOWLEDGE_DESCRIPTION = (
    "Retrieve a knowledge document by exact name. Use when you know the document "
    "exists and want the full content. For open-ended search, use search_knowledge instead."
)

SEARCH_KNOWLEDGE_DESCRIPTION = (
    "Search knowledge documents by semantic similarity. Use when you want to find "
    "relevant project or system documentation without knowing the exact name."
)


LIST_KNOWLEDGE_BASES_DESCRIPTION = (
    "List all knowledge bases. Use when you want to see all the knowledge bases available to you."
)

APPEND_TO_KNOWLEDGE_DESCRIPTION = (
    "Append content to a knowledge document. Use when you want to add more information to a document without overwriting it."
)

@register({
    "type": "function",
    "function": {
        "name": "upsert_knowledge",
        "description": UPSERT_KNOWLEDGE_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Snake_case identifier for the document (e.g. 'project_xyz', 'home_network'). Used for exact retrieval and deduplication.",
                },
                "content": {
                    "type": "string",
                    "description": "Full document content. Replaces existing content entirely — include everything, not just the update.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["channel", "global", "bot", "private"],
                    "description": (
                        "'channel' (default) = any bot in this channel can access it. "
                        "'global' = any bot in any channel. "
                        "'bot' = this bot only, all channels. "
                        "'private' = this bot in this channel only."
                    ),
                    "default": "channel",
                },
            },
            "required": ["name", "content"],
        },
    },
})
async def upsert_knowledge_tool(name: str, content: str, scope: str = "channel") -> str:
    raise NotImplementedError("upsert_knowledge must be called via call_knowledge_tool")


@register({
    "type": "function",
    "function": {
        "name": "append_to_knowledge",
        "description": APPEND_TO_KNOWLEDGE_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Snake_case identifier for the document (e.g. 'project_xyz', 'home_network'). Used for exact retrieval and deduplication.",
                },
                "content": {
                    "type": "string",
                    "description": "Content to append to the document. Will be added to the end of the document.",
                },
            },
            "required": ["name", "content"],
        },
    },
})
async def append_to_knowledge_tool(name: str, content: str) -> str:
    raise NotImplementedError("upsert_knowledge must be called via call_knowledge_tool")



@register({
    "type": "function",
    "function": {
        "name": "get_knowledge",
        "description": GET_KNOWLEDGE_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Exact snake_case name of the knowledge document to retrieve.",
                },
            },
            "required": ["name"],
        },
    },
})
async def get_knowledge_tool(name: str) -> str:
    raise NotImplementedError("get_knowledge must be called via call_knowledge_tool")


@register({
    "type": "function",
    "function": {
        "name": "list_knowledge_bases",
        "description": LIST_KNOWLEDGE_BASES_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
            },
            "required": [],
        },
    },
})
async def list_knowledge_bases_tool() -> str:
    raise NotImplementedError("list_knowledge_bases must be called via call_knowledge_tool")


@register({
    "type": "function",
    "function": {
        "name": "search_knowledge",
        "description": SEARCH_KNOWLEDGE_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query (e.g. 'CI/CD pipeline setup', 'home network devices').",
                },
            },
            "required": ["query"],
        },
    },
})
async def search_knowledge_tool(query: str) -> str:
    raise NotImplementedError("search_knowledge must be called via call_knowledge_tool")


@register({
    "type": "function",
    "function": {
        "name": "pin_knowledge",
        "description": (
            "Pin a knowledge document so it is always injected into context, regardless of semantic similarity. "
            "Use when a document should always be available (e.g. formatting rules, style guides, always-on reference). "
            "Scope controls when the pin applies: 'bot' = always for this bot, 'channel' = always for this Slack channel/client, "
            "'bot_channel' = only for this bot in this specific channel."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Exact name of the knowledge document to pin.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["bot", "channel", "bot_channel"],
                    "description": "'bot' pins for all channels, 'channel' pins for all bots in this channel, 'bot_channel' pins for this bot+channel only.",
                },
            },
            "required": ["name", "scope"],
        },
    },
})
async def pin_knowledge_tool(name: str, scope: str) -> str:
    raise NotImplementedError("pin_knowledge must be called via call_knowledge_tool")


@register({
    "type": "function",
    "function": {
        "name": "unpin_knowledge",
        "description": "Remove a knowledge pin so the document returns to similarity-based retrieval only.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Exact name of the knowledge document to unpin.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["bot", "channel", "bot_channel"],
                    "description": "Must match the scope used when pinning.",
                },
            },
            "required": ["name", "scope"],
        },
    },
})
async def unpin_knowledge_tool(name: str, scope: str) -> str:
    raise NotImplementedError("unpin_knowledge must be called via call_knowledge_tool")


@register({
    "type": "function",
    "function": {
        "name": "set_knowledge_threshold",
        "description": (
            "Adjust the cosine similarity threshold used to decide whether knowledge documents are injected into context. "
            "Raise the threshold (e.g. to 0.6–0.7) if irrelevant knowledge is being injected for unrelated questions. "
            "Lower it (e.g. to 0.3–0.35) if relevant knowledge is being missed. "
            "Typical useful range: 0.35–0.75. Default is 0.45. "
            "Changes take effect immediately on the next request."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "threshold": {
                    "type": "number",
                    "description": "New similarity threshold (0.0–1.0). Higher = more selective.",
                },
            },
            "required": ["threshold"],
        },
    },
})
async def set_knowledge_threshold(threshold: float) -> str:
    from app.agent.bots import reload_bots
    from app.agent.context import current_bot_id
    from app.db.engine import async_session
    from app.db.models import Bot as BotRow
    from sqlalchemy import select as sa_select

    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."})
    if not (0.0 <= threshold <= 1.0):
        return json.dumps({"error": "Threshold must be between 0.0 and 1.0."})

    async with async_session() as db:
        row = (await db.execute(sa_select(BotRow).where(BotRow.id == bot_id))).scalar_one_or_none()
        if row is None:
            return json.dumps({"error": f"Bot '{bot_id}' not found."})
        cfg = dict(row.knowledge_config or {})
        old = cfg.get("similarity_threshold", 0.45)
        cfg["similarity_threshold"] = threshold
        row.knowledge_config = cfg
        await db.commit()

    reload_bots()
    return f"Knowledge similarity threshold updated: {old} → {threshold}. Takes effect on the next request."


async def call_knowledge_tool(
    name: str,
    arguments_json: str,
    bot_id: str,
    client_id: str,
    similarity_threshold: float = 0.45,
) -> str:
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError:
        return "Invalid tool arguments."

    if name == "upsert_knowledge":
        doc_name = (args.get("name") or "").strip()
        content = (args.get("content") or "").strip()
        scope = (args.get("scope") or "private").strip()
        if not doc_name:
            return "No name provided; knowledge not saved."
        if not content:
            return "No content provided; knowledge not saved."
        # Derive scoped bot_id/client_id from scope
        scoped_bot_id = None if scope in ("channel", "global") else bot_id
        scoped_client_id = None if scope in ("bot", "global") else client_id
        ok, err = await upsert_knowledge(
            name=doc_name,
            content=content,
            bot_id=scoped_bot_id,
            client_id=scoped_client_id,
        )
        if ok:
            return f"Knowledge '{doc_name}' saved (scope={scope})."
        return f"Failed to save knowledge: {err}" if err else "Failed to save knowledge."

    if name == "get_knowledge":
        doc_name = (args.get("name") or "").strip()
        if not doc_name:
            return "No name provided."
        result = await get_knowledge_by_name(doc_name, bot_id, client_id)
        return result if result else f"No knowledge document found with name '{doc_name}'."

    if name == "list_knowledge_bases":
        result = await list_knowledge_bases(bot_id, client_id)
        if not result:
            return "No knowledge bases found."
        return "\n".join(result)

    if name == "append_to_knowledge":
        doc_name = (args.get("name") or "").strip()
        content = (args.get("content") or "").strip()
        if not doc_name:
            return "No name provided."
        if not content:
            return "No content provided."
        ok, err = await append_to_knowledge(doc_name, content, bot_id, client_id)
        if ok:
            return f"Content appended to knowledge document '{doc_name}'."
        return f"Failed to append to knowledge document: {err}" if err else "Failed to append to knowledge document."

    if name == "search_knowledge":
        query = (args.get("query") or "").strip()
        if not query:
            return "No query provided."
        chunks, _ = await retrieve_knowledge(
            query=query,
            bot_id=bot_id,
            client_id=client_id,
            similarity_threshold=similarity_threshold,
        )
        if not chunks:
            return "No relevant knowledge found."
        return "Relevant knowledge:\n\n" + "\n\n---\n\n".join(chunks)

    if name == "pin_knowledge":
        doc_name = (args.get("name") or "").strip()
        scope = (args.get("scope") or "bot").strip()
        if not doc_name:
            return "No name provided."
        pin_bot_id = bot_id if scope in ("bot", "bot_channel") else None
        pin_client_id = client_id if scope in ("channel", "bot_channel") else None
        ok, err = await create_knowledge_pin(doc_name, pin_bot_id, pin_client_id)
        if ok:
            return f"Knowledge '{doc_name}' pinned (scope={scope})."
        return f"Failed to pin: {err}" if err else "Failed to pin."

    if name == "unpin_knowledge":
        doc_name = (args.get("name") or "").strip()
        scope = (args.get("scope") or "bot").strip()
        if not doc_name:
            return "No name provided."
        pin_bot_id = bot_id if scope in ("bot", "bot_channel") else None
        pin_client_id = client_id if scope in ("channel", "bot_channel") else None
        removed = await delete_knowledge_pin(doc_name, pin_bot_id, pin_client_id)
        return f"Knowledge '{doc_name}' unpinned." if removed else f"No matching pin found for '{doc_name}' (scope={scope})."

    return json.dumps({"error": f"Unknown knowledge tool: {name}"})
