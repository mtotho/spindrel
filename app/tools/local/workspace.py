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
            "Semantically search files in the bot's workspace. "
            "Returns the most relevant chunks for the query with file paths, "
            "symbols, and line numbers. Use this to find functions, classes, "
            "config values, documentation, or any text in the workspace."
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
})
async def search_workspace(query: str, top_k: int | None = None) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."})

    from app.agent.bots import get_bot
    bot = get_bot(bot_id)

    if not bot.workspace.enabled:
        return json.dumps({"error": "Workspace is not enabled for this bot."})
    if not bot.workspace.indexing.enabled:
        return json.dumps({"error": "Workspace indexing is not enabled for this bot."})

    from app.services.workspace import workspace_service
    from app.agent.fs_indexer import retrieve_filesystem_context

    root = workspace_service.get_workspace_root(bot_id)
    threshold = bot.workspace.indexing.similarity_threshold
    k = top_k or bot.workspace.indexing.top_k

    chunks, best_sim = await retrieve_filesystem_context(
        query, bot_id, roots=[root], top_k=k, threshold=threshold,
    )
    if not chunks:
        return "No relevant results found."
    header = f"Found {len(chunks)} result(s) (best similarity: {best_sim:.3f}):\n\n"
    return header + "\n\n---\n\n".join(chunks)


@register({
    "type": "function",
    "function": {
        "name": "reindex_workspace",
        "description": (
            "Force an immediate full re-index of the bot's workspace files. "
            "Use after making significant file changes or to force a refresh. "
            "Returns stats: indexed, skipped, removed, errors."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
})
async def reindex_workspace() -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."})

    from app.agent.bots import get_bot
    bot = get_bot(bot_id)

    if not bot.workspace.enabled:
        return json.dumps({"error": "Workspace is not enabled for this bot."})
    if not bot.workspace.indexing.enabled:
        return json.dumps({"error": "Workspace indexing is not enabled for this bot."})

    from app.services.workspace import workspace_service
    from app.agent.fs_indexer import index_directory

    root = workspace_service.get_workspace_root(bot_id)
    patterns = bot.workspace.indexing.patterns

    stats = await index_directory(root, bot_id, patterns, force=True)
    return json.dumps(stats)
