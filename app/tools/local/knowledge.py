import json
import logging
import uuid

from app.agent.knowledge import (
    append_to_knowledge,
    create_knowledge_pin,
    delete_knowledge_pin,
    get_knowledge_by_name,
    list_knowledge_bases,
    retrieve_knowledge,
    set_knowledge_similarity_for_match,
    upsert_knowledge,
)
from app.tools.registry import register

logger = logging.getLogger(__name__)

UPSERT_KNOWLEDGE_DESCRIPTION = (
    "Create or update a knowledge document about a topic, project, or system. "
    "Use for structured, multi-faceted information that will grow over time — "
    "e.g. 'project_xyz_architecture', 'home_network_layout', 'bayada_cicd_setup'. "
    "Unlike memories (single facts), knowledge docs are living documents you update "
    "as understanding deepens. Documents are always scoped to this chat session only "
    "(not visible to other sessions); created_by_bot records which bot wrote them."
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
                "similarity_threshold": {
                    "type": "number",
                    "description": "Optional. Minimum cosine similarity (0–1) for this document in semantic search. Omit to use server default or keep existing.",
                },
            },
            "required": ["name", "content"],
        },
    },
})
async def upsert_knowledge_tool(name: str, content: str) -> str:
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
        "name": "set_knowledge_similarity_threshold",
        "description": (
            "Set the minimum cosine similarity (0–1) for one knowledge document in the current session scope. "
            "Higher = stricter (fewer injections). Lower = looser. Per-document; does not affect other knowledge bases."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Exact snake_case name of the knowledge document.",
                },
                "threshold": {
                    "type": "number",
                    "description": "Minimum similarity 0.0–1.0 for semantic retrieval of this doc.",
                },
            },
            "required": ["name", "threshold"],
        },
    },
})
async def set_knowledge_similarity_threshold_tool(name: str, threshold: float) -> str:
    raise NotImplementedError("use call_knowledge_tool")


async def call_knowledge_tool(
    name: str,
    arguments_json: str,
    bot_id: str,
    client_id: str,
    *,
    session_id: uuid.UUID | None = None,
    fallback_threshold: float = 0.45,
) -> str:
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError:
        return "Invalid tool arguments."

    if name == "upsert_knowledge":
        doc_name = (args.get("name") or "").strip()
        content = (args.get("content") or "").strip()
        if not doc_name:
            return "No name provided; knowledge not saved."
        if not content:
            return "No content provided; knowledge not saved."
        if not session_id:
            return "Cannot save knowledge without an active session."
        raw_sim = args.get("similarity_threshold")
        sim_thr: float | None = None
        if raw_sim is not None and str(raw_sim).strip() != "":
            try:
                sim_thr = float(raw_sim)
            except (TypeError, ValueError):
                return "Invalid similarity_threshold; omit or use a number 0–1."
            if not (0.0 <= sim_thr <= 1.0):
                return "similarity_threshold must be between 0.0 and 1.0."
        ok, err = await upsert_knowledge(
            name=doc_name,
            content=content,
            bot_id=bot_id,
            client_id=client_id,
            session_id=session_id,
            created_by_bot=bot_id,
            similarity_threshold=sim_thr,
        )
        if ok:
            return f"Knowledge '{doc_name}' saved for this session."
        return f"Failed to save knowledge: {err}" if err else "Failed to save knowledge."

    if name == "get_knowledge":
        doc_name = (args.get("name") or "").strip()
        if not doc_name:
            return "No name provided."
        result = await get_knowledge_by_name(
            doc_name, bot_id, client_id, session_id=session_id
        )
        return result if result else f"No knowledge document found with name '{doc_name}'."

    if name == "list_knowledge_bases":
        result = await list_knowledge_bases(bot_id, client_id, session_id=session_id)
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
        if not session_id:
            return "Cannot append knowledge without an active session."
        ok, err = await append_to_knowledge(
            doc_name, content, bot_id, client_id, session_id=session_id
        )
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
            fallback_threshold=fallback_threshold,
            session_id=session_id,
        )
        if not chunks:
            return "No relevant knowledge found."
        return "Relevant knowledge:\n\n" + "\n\n---\n\n".join(chunks)

    if name == "set_knowledge_similarity_threshold":
        doc_name = (args.get("name") or "").strip()
        raw_t = args.get("threshold")
        if not doc_name:
            return "No name provided."
        try:
            thr = float(raw_t)
        except (TypeError, ValueError):
            return "Invalid threshold."
        if not (0.0 <= thr <= 1.0):
            return "Threshold must be between 0.0 and 1.0."
        if not session_id:
            return "No active session."
        ok, err = await set_knowledge_similarity_for_match(
            doc_name, bot_id, client_id, session_id, thr
        )
        if ok:
            return f"Knowledge {doc_name!r} similarity threshold set to {thr}."
        return err or "Failed to update threshold."

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
