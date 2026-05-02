"""Workspace tools — semantic search and re-index over the bot's workspace."""
from __future__ import annotations

import json

from app.agent.context import current_bot_id
from app.tools.registry import register

_SEARCH_RETURNS = {
    "type": "object",
    "properties": {
        "count": {"type": "integer"},
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "score": {"type": "number"},
                    "snippet": {"type": "string"},
                },
                "required": ["file_path", "snippet"],
            },
        },
        "best_similarity": {"type": "number"},
        "message": {"type": "string"},
        "error": {"type": "string"},
    },
    "required": ["count", "results"],
}


def _parse_chunk_fields(chunk: str) -> tuple[str, str]:
    """Return (file_path, snippet) from a formatted fs chunk string."""
    sep = "\n\n"
    idx = chunk.find(sep)
    if chunk.startswith("[File: ") and idx > 0:
        location = chunk[7:idx - 1]  # strip "[File: " prefix and "]" suffix
        fp = location.split(" (")[0].split(" L")[0]
        snippet = chunk[idx + 2:].strip()
        return fp, snippet
    return "", chunk.strip()


@register({
    "type": "function",
    "function": {
        "name": "search_workspace",
        "description": (
            "Search indexed workspace files using hybrid semantic + keyword search. "
            "Covers files matching the bot's indexing segments (configured workspace directories). "
            "Does NOT search memory files (use search_memory) or channel workspace files "
            "(use search_channel_workspace)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum number of results to return. Default: server setting.",
                },
            },
            "required": ["query"],
        },
    },
}, requires_bot_context=True, tool_metadata={
    "domains": ["channel_workspace"],
    "exposure": "ambient",
    "auto_inject": ["channel_workspace"],
}, returns=_SEARCH_RETURNS)
async def search_workspace(query: str, top_k: int | None = None) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"count": 0, "results": [], "error": "No bot context available."}, ensure_ascii=False)

    from app.agent.bots import get_bot
    bot = get_bot(bot_id)

    if not bot.workspace.enabled:
        return json.dumps({"count": 0, "results": [], "error": "Workspace is not enabled for this bot."}, ensure_ascii=False)
    if not bot.workspace.indexing.enabled:
        return json.dumps({"count": 0, "results": [], "error": "Workspace indexing is not enabled for this bot."}, ensure_ascii=False)

    from app.agent.fs_indexer import retrieve_filesystem_context
    from app.services.bot_indexing import resolve_for

    plan = resolve_for(bot, scope="workspace")
    assert plan is not None  # workspace.enabled checked above
    k = top_k or plan.top_k

    chunks, best_sim = await retrieve_filesystem_context(
        query, bot_id, roots=list(plan.roots), top_k=k,
        threshold=plan.similarity_threshold,
        embedding_model=plan.embedding_model,
        segments=plan.segments,
    )
    if not chunks:
        return json.dumps({"count": 0, "results": [], "message": "No relevant results found."}, ensure_ascii=False)

    items = []
    for chunk in chunks:
        fp, snippet = _parse_chunk_fields(chunk)
        items.append({"file_path": fp, "snippet": snippet})
    return json.dumps({"count": len(items), "results": items, "best_similarity": round(best_sim, 3)}, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "search_bot_knowledge",
        "description": (
            "Search THIS bot's knowledge-base/ folder — the convention-based folder "
            "every bot has for curated, long-lived facts that travel with the bot "
            "across every channel. Prefer this over search_workspace when the user "
            "is asking 'what do you know about X' rather than 'where did we do X'. "
            "Scope is narrow: only files under knowledge-base/ (or bots/{id}/knowledge-base/ "
            "for shared-workspace bots). Use search_channel_knowledge for channel-specific facts."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language lookup query.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Maximum number of results to return. Default: server setting.",
                },
            },
            "required": ["query"],
        },
    },
}, requires_bot_context=True, returns=_SEARCH_RETURNS)
async def search_bot_knowledge(query: str, top_k: int | None = None) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"count": 0, "results": [], "error": "No bot context available."}, ensure_ascii=False)

    query = (query or "").strip()
    if not query:
        return json.dumps({"count": 0, "results": [], "error": "No search query provided."}, ensure_ascii=False)

    from app.agent.bots import get_bot
    bot = get_bot(bot_id)
    if not bot or not bot.workspace.enabled:
        return json.dumps({"count": 0, "results": [], "error": "Bot knowledge search is not available (workspace disabled)."}, ensure_ascii=False)
    if not bot.workspace.indexing.enabled:
        return json.dumps({"count": 0, "results": [], "error": "Bot knowledge search is not available (indexing disabled)."}, ensure_ascii=False)

    from app.services.bot_indexing import resolve_for
    from app.services.memory_search import hybrid_memory_search
    from app.services.workspace import workspace_service

    plan = resolve_for(bot, scope="workspace")
    assert plan is not None  # workspace.enabled checked above
    kb_prefix = workspace_service.get_bot_knowledge_base_index_prefix(bot)

    try:
        results = await hybrid_memory_search(
            query=query,
            bot_id=bot_id,
            roots=list(plan.roots),
            memory_prefix=kb_prefix,
            embedding_model=plan.embedding_model,
            top_k=top_k or plan.top_k,
        )
    except Exception as exc:
        return json.dumps({"count": 0, "results": [], "error": f"Bot knowledge search ERROR: {exc}"}, ensure_ascii=False)

    if not results:
        return json.dumps({"count": 0, "results": [], "message": "No matching content in this bot's knowledge base."}, ensure_ascii=False)

    items = []
    for r in results:
        snippet = r.content
        if snippet.startswith("# "):
            first_nl = snippet.find("\n")
            if first_nl > 0:
                snippet = snippet[first_nl + 1:]
        items.append({"file_path": r.file_path, "score": round(r.score, 3), "snippet": snippet.strip()})
    return json.dumps({"count": len(items), "results": items}, ensure_ascii=False)
