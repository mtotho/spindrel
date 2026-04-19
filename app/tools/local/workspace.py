"""Workspace tools — semantic search and re-index over the bot's workspace."""
from __future__ import annotations

import json

from app.agent.context import current_bot_id
from app.tools.registry import register


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
}, requires_bot_context=True)
async def search_workspace(query: str, top_k: int | None = None) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."}, ensure_ascii=False)

    from app.agent.bots import get_bot
    bot = get_bot(bot_id)

    if not bot.workspace.enabled:
        return json.dumps({"error": "Workspace is not enabled for this bot."}, ensure_ascii=False)
    if not bot.workspace.indexing.enabled:
        return json.dumps({"error": "Workspace indexing is not enabled for this bot."}, ensure_ascii=False)

    from app.services.workspace import workspace_service
    from app.services.workspace_indexing import resolve_indexing, get_all_roots
    from app.agent.fs_indexer import retrieve_filesystem_context

    _resolved = resolve_indexing(bot.workspace.indexing, bot._workspace_raw, bot._ws_indexing_config)
    roots = get_all_roots(bot, workspace_service)
    threshold = _resolved["similarity_threshold"]
    k = top_k or _resolved["top_k"]

    chunks, best_sim = await retrieve_filesystem_context(
        query, bot_id, roots=roots, top_k=k, threshold=threshold,
        embedding_model=_resolved["embedding_model"],
        segments=_resolved.get("segments"),
    )
    if not chunks:
        return "No relevant results found."
    header = f"Found {len(chunks)} result(s) (best similarity: {best_sim:.3f}):\n\n"
    return header + "\n\n---\n\n".join(chunks)


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
}, requires_bot_context=True)
async def search_bot_knowledge(query: str, top_k: int | None = None) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."}, ensure_ascii=False)

    query = (query or "").strip()
    if not query:
        return "No search query provided."

    from app.agent.bots import get_bot
    bot = get_bot(bot_id)
    if not bot or not bot.workspace.enabled:
        return "Bot knowledge search is not available (workspace disabled)."
    if not bot.workspace.indexing.enabled:
        return "Bot knowledge search is not available (indexing disabled)."

    from app.services.workspace import workspace_service
    from app.services.workspace_indexing import resolve_indexing, get_all_roots
    from app.services.memory_search import hybrid_memory_search

    _resolved = resolve_indexing(bot.workspace.indexing, bot._workspace_raw, bot._ws_indexing_config)
    roots = get_all_roots(bot, workspace_service)
    kb_prefix = workspace_service.get_bot_knowledge_base_index_prefix(bot)

    try:
        results = await hybrid_memory_search(
            query=query,
            bot_id=bot_id,
            roots=roots,
            memory_prefix=kb_prefix,
            embedding_model=_resolved["embedding_model"],
            top_k=top_k or _resolved["top_k"],
        )
    except Exception as exc:
        return f"Bot knowledge search ERROR: {exc}"

    if not results:
        return "No matching content in this bot's knowledge base."

    lines = []
    for r in results:
        content = r.content
        if content.startswith("# "):
            first_nl = content.find("\n")
            if first_nl > 0:
                content = content[first_nl + 1:]
        lines.append(f"**{r.file_path}** (score: {r.score:.3f})\n{content.strip()}")
    return "\n\n---\n\n".join(lines)
