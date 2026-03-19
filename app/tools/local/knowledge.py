import json
import logging

from app.agent.knowledge import get_knowledge_by_name, retrieve_knowledge, upsert_knowledge, list_knowledge_bases
from app.tools.registry import register

logger = logging.getLogger(__name__)

UPSERT_KNOWLEDGE_DESCRIPTION = (
    "Create or update a knowledge document about a topic, project, or system. "
    "Use for structured, multi-faceted information that will grow over time — "
    "e.g. 'project_xyz_architecture', 'home_network_layout', 'bayada_cicd_setup'. "
    "Unlike memories (single facts), knowledge docs are living documents you update "
    "as understanding deepens. Set shared=true to make it available across all bots."
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
                "shared": {
                    "type": "boolean",
                    "description": "If true, document is available to all bots. Defaults to false (bot-scoped).",
                    "default": False,
                },
            },
            "required": ["name", "content"],
        },
    },
})
async def upsert_knowledge_tool(name: str, content: str, shared: bool = False) -> str:
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


async def call_knowledge_tool(
    name: str,
    arguments_json: str,
    bot_id: str,
    client_id: str,
    cross_bot: bool = False,
    cross_client: bool = False,
    similarity_threshold: float = 0.45,
) -> str:
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError:
        return "Invalid tool arguments."

    if name == "upsert_knowledge":
        doc_name = (args.get("name") or "").strip()
        content = (args.get("content") or "").strip()
        shared = bool(args.get("shared", False))
        if not doc_name:
            return "No name provided; knowledge not saved."
        if not content:
            return "No content provided; knowledge not saved."
        ok, err = await upsert_knowledge(
            name=doc_name,
            content=content,
            bot_id=bot_id,
            client_id=client_id,
            shared=shared,
        )
        if ok:
            return f"Knowledge '{doc_name}' saved."
        return f"Failed to save knowledge: {err}" if err else "Failed to save knowledge."

    if name == "get_knowledge":
        doc_name = (args.get("name") or "").strip()
        if not doc_name:
            return "No name provided."
        result = await get_knowledge_by_name(doc_name, bot_id, client_id,
         is_cross_client=cross_client, is_cross_bot=cross_bot)
        return result if result else f"No knowledge document found with name '{doc_name}'."

    if name == "list_knowledge_bases":
        result = await list_knowledge_bases(bot_id, client_id,
            is_cross_client=cross_client, is_cross_bot=cross_bot)
        if not result:
            return "No knowledge bases found."
        return "\n".join(result)

    if name == "search_knowledge":
        query = (args.get("query") or "").strip()
        if not query:
            return "No query provided."
        chunks = await retrieve_knowledge(
            query=query,
            bot_id=bot_id,
            client_id=client_id,
            cross_bot=cross_bot,
            cross_client=cross_client,
            similarity_threshold=similarity_threshold,
        )
        if not chunks:
            return "No relevant knowledge found."
        return "Relevant knowledge:\n\n" + "\n\n---\n\n".join(chunks)

    return json.dumps({"error": f"Unknown knowledge tool: {name}"})
