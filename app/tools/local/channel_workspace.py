"""Local tools for channel workspace: search_channel_archive, search_channel_workspace, list_channels."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.agent.context import current_bot_id, current_channel_id
from app.tools.registry import register

logger = logging.getLogger(__name__)

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
        "message": {"type": "string"},
        "error": {"type": "string"},
    },
    "required": ["count", "results"],
}


def _format_search_results(results) -> str:
    """Format hybrid_memory_search results as a structured JSON string."""
    items = []
    for r in results:
        snippet = r.content
        if snippet.startswith("# "):
            first_nl = snippet.find("\n")
            if first_nl > 0:
                snippet = snippet[first_nl + 1:]
        items.append({"file_path": r.file_path, "score": round(r.score, 3), "snippet": snippet.strip()})
    return json.dumps({"count": len(items), "results": items}, ensure_ascii=False)


async def _get_bot_and_roots(channel_id: str | None = None) -> tuple:
    """Resolve bot, channel_id, workspace root, and embedding model.

    When *channel_id* belongs to a different bot AND the calling bot has
    ``cross_workspace_access``, we resolve using the *owning* bot's workspace
    root so the search hits the correct directory.
    """
    bot_id = current_bot_id.get()
    ch_id = channel_id or (str(current_channel_id.get()) if current_channel_id.get() else None)
    if not bot_id or not ch_id:
        return None, None, None, None

    from app.agent.bots import get_bot
    bot = get_bot(bot_id)
    if not bot or not bot.workspace.enabled:
        return None, None, None, None

    # Determine the effective bot whose workspace root to use.
    effective_bot = bot
    if channel_id and bot.cross_workspace_access:
        owner_bot = await _resolve_channel_owner_bot(channel_id, bot_id)
        if owner_bot is not None:
            effective_bot = owner_bot

    from app.services.bot_indexing import resolve_for
    from app.services.channel_workspace import _get_ws_root

    ws_root = str(Path(_get_ws_root(effective_bot)).resolve())
    plan = resolve_for(effective_bot, scope="workspace")
    embedding_model = plan.embedding_model if plan is not None else None
    return bot, ch_id, ws_root, embedding_model


async def _resolve_channel_owner_bot(channel_id: str, caller_bot_id: str):
    """Look up the bot that owns *channel_id*. Returns its BotConfig or None.

    Returns None if the channel belongs to the caller (no switch needed)
    or if the owning bot can't be resolved.
    """
    from app.db.engine import async_session as _async_session
    from sqlalchemy import select
    from app.db.models import Channel

    async with _async_session() as db:
        row = (await db.execute(
            select(Channel.bot_id).where(Channel.id == channel_id)
        )).first()

    if not row:
        return None
    owner_bot_id = str(row.bot_id)
    if owner_bot_id == caller_bot_id:
        return None  # same bot, no switch needed

    from app.agent.bots import get_bot
    owner_bot = get_bot(owner_bot_id)
    if not owner_bot or not owner_bot.workspace.enabled:
        return None
    return owner_bot


@register({
    "type": "function",
    "function": {
        "name": "search_channel_archive",
        "description": (
            "Search the current channel's archived workspace files. "
            "Searches only the archive/ subdirectory of the channel workspace. "
            "For all channel files (active + archived), use search_channel_workspace."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for archived workspace files.",
                },
            },
            "required": ["query"],
        },
    },
}, requires_bot_context=True, requires_channel_context=True, returns=_SEARCH_RETURNS)
async def search_channel_archive(query: str) -> str:
    """Search archived workspace files for the current channel."""
    bot, ch_id, ws_root, embedding_model = await _get_bot_and_roots()
    if not bot or not ch_id:
        return json.dumps({"count": 0, "results": [], "error": "Archive search is not available (no channel workspace context)."}, ensure_ascii=False)

    query = (query or "").strip()
    if not query:
        return json.dumps({"count": 0, "results": [], "error": "No search query provided."}, ensure_ascii=False)

    from app.services.channel_workspace import get_channel_workspace_index_prefix
    from app.services.channel_workspace_indexing import _get_channel_index_bot_id
    from app.services.memory_search import hybrid_memory_search

    sentinel = _get_channel_index_bot_id(ch_id)
    prefix = get_channel_workspace_index_prefix(ch_id) + "/archive"

    try:
        results = await hybrid_memory_search(
            query=query,
            bot_id=sentinel,
            roots=[ws_root],
            memory_prefix=prefix,
            embedding_model=embedding_model,
            top_k=10,
        )
    except Exception as exc:
        logger.error("search_channel_archive failed for channel %s: %s", ch_id, exc)
        return json.dumps({"count": 0, "results": [], "error": f"Archive search ERROR: {exc}"}, ensure_ascii=False)

    if not results:
        import asyncio
        from app.services.channel_workspace_indexing import index_channel_workspace
        asyncio.create_task(index_channel_workspace(ch_id, bot))
        return json.dumps({"count": 0, "results": [], "message": "No matching archived content found."}, ensure_ascii=False)

    return _format_search_results(results)


@register({
    "type": "function",
    "function": {
        "name": "search_channel_workspace",
        "description": (
            "Search a channel's workspace files (both active and archived). "
            "If no channel_id is provided, searches the current channel. "
            "For bot workspace search, use search_workspace instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for workspace files.",
                },
                "channel_id": {
                    "type": "string",
                    "description": "Optional channel ID to search. Defaults to current channel.",
                },
            },
            "required": ["query"],
        },
    },
}, requires_bot_context=True, requires_channel_context=True, returns=_SEARCH_RETURNS)
async def search_channel_workspace(query: str, channel_id: str | None = None) -> str:
    """Search channel workspace files (active + archive)."""
    bot, ch_id, ws_root, embedding_model = await _get_bot_and_roots(channel_id)
    if not bot or not ch_id:
        return json.dumps({"count": 0, "results": [], "error": "Channel workspace search is not available (no workspace context)."}, ensure_ascii=False)

    query = (query or "").strip()
    if not query:
        return json.dumps({"count": 0, "results": [], "error": "No search query provided."}, ensure_ascii=False)

    from app.services.channel_workspace import get_channel_workspace_index_prefix
    from app.services.channel_workspace_indexing import _get_channel_index_bot_id
    from app.services.memory_search import hybrid_memory_search

    sentinel = _get_channel_index_bot_id(ch_id)
    prefix = get_channel_workspace_index_prefix(ch_id)

    try:
        results = await hybrid_memory_search(
            query=query,
            bot_id=sentinel,
            roots=[ws_root],
            memory_prefix=prefix,
            embedding_model=embedding_model,
            top_k=10,
        )
    except Exception as exc:
        logger.error("search_channel_workspace failed for channel %s: %s", ch_id, exc)
        return json.dumps({"count": 0, "results": [], "error": f"Channel workspace search ERROR: {exc}"}, ensure_ascii=False)

    if not results:
        return json.dumps({"count": 0, "results": [], "message": "No matching workspace content found."}, ensure_ascii=False)

    return _format_search_results(results)


@register({
    "type": "function",
    "function": {
        "name": "search_channel_knowledge",
        "description": (
            "Search THIS channel's knowledge-base/ folder — the convention-based folder "
            "every channel has for curated, long-lived facts that stay scoped to the room. "
            "Prefer this over search_channel_workspace when the user is asking 'what do you "
            "know about X' rather than 'where did we do X'. Scope is narrow: only files under "
            "channels/{channel_id}/knowledge-base/. Use search_bot_knowledge for facts that "
            "should travel with the bot across channels."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language lookup query.",
                },
            },
            "required": ["query"],
        },
    },
}, requires_bot_context=True, requires_channel_context=True, returns=_SEARCH_RETURNS)
async def search_channel_knowledge(query: str) -> str:
    """Search the current channel's knowledge-base/ folder."""
    bot, ch_id, ws_root, embedding_model = await _get_bot_and_roots()
    if not bot or not ch_id:
        return json.dumps({"count": 0, "results": [], "error": "Channel knowledge search is not available (no channel workspace context)."}, ensure_ascii=False)

    query = (query or "").strip()
    if not query:
        return json.dumps({"count": 0, "results": [], "error": "No search query provided."}, ensure_ascii=False)

    from app.services.channel_workspace import get_channel_knowledge_base_index_prefix
    from app.services.channel_workspace_indexing import _get_channel_index_bot_id
    from app.services.memory_search import hybrid_memory_search

    sentinel = _get_channel_index_bot_id(ch_id)
    prefix = get_channel_knowledge_base_index_prefix(ch_id)

    try:
        results = await hybrid_memory_search(
            query=query,
            bot_id=sentinel,
            roots=[ws_root],
            memory_prefix=prefix,
            embedding_model=embedding_model,
            top_k=10,
        )
    except Exception as exc:
        logger.error("search_channel_knowledge failed for channel %s: %s", ch_id, exc)
        return json.dumps({"count": 0, "results": [], "error": f"Channel knowledge search ERROR: {exc}"}, ensure_ascii=False)

    if not results:
        return json.dumps({"count": 0, "results": [], "message": "No matching content in this channel's knowledge base."}, ensure_ascii=False)

    return _format_search_results(results)


@register({
    "type": "function",
    "function": {
        "name": "list_channels",
        "description": (
            "List all channels this bot belongs to (primary and member). "
            "Returns channel IDs, display names, and flags (workspace enabled, current, member). "
            "Use channel IDs with read_conversation_history, search_channel_workspace, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
}, requires_bot_context=True, requires_channel_context=True, returns={
    "type": "object",
    "properties": {
        "count": {"type": "integer"},
        "channels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "client_id": {"type": "string"},
                    "bot_id": {"type": "string"},
                    "bot_name": {"type": "string"},
                    "is_current": {"type": "boolean"},
                    "is_member": {"type": "boolean"},
                },
                "required": ["id"],
            },
        },
        "error": {"type": "string"},
    },
    "required": ["count", "channels"],
})
async def list_channels() -> str:
    """List all channels the bot belongs to (primary + member)."""
    bot_id = current_bot_id.get()
    my_ch_id = str(current_channel_id.get()) if current_channel_id.get() else None
    if not bot_id:
        return json.dumps({"count": 0, "channels": [], "error": "Not available (no bot context)."}, ensure_ascii=False)

    from app.agent.bots import get_bot
    bot = get_bot(bot_id)
    cross_access = bot.cross_workspace_access if bot else False

    from app.db.engine import async_session
    from sqlalchemy import select
    from app.db.models import Bot as BotRow, Channel

    async with async_session() as db:
        if cross_access:
            stmt = (
                select(
                    Channel.id, Channel.name, Channel.client_id,
                    Channel.bot_id,
                    BotRow.name.label("bot_name"),
                )
                .join(BotRow, BotRow.id == Channel.bot_id)
                .order_by(BotRow.name, Channel.name)
            )
        else:
            from app.services.channels import bot_channel_filter
            stmt = (
                select(
                    Channel.id, Channel.name, Channel.client_id,
                    Channel.bot_id,
                )
                .where(bot_channel_filter(bot_id))
                .order_by(Channel.name)
            )
        rows = (await db.execute(stmt)).all()

    if not rows:
        return json.dumps({"count": 0, "channels": []}, ensure_ascii=False)

    channels = []
    for row in rows:
        ch_str = str(row.id)
        entry: dict = {
            "id": ch_str,
            "name": row.name or row.client_id or "",
            "client_id": row.client_id or "",
            "bot_id": str(row.bot_id),
            "is_current": ch_str == my_ch_id,
        }
        if cross_access:
            entry["bot_name"] = getattr(row, "bot_name", None) or str(row.bot_id)
            entry["is_member"] = str(row.bot_id) != bot_id
        else:
            entry["is_member"] = str(row.bot_id) != bot_id
        channels.append(entry)

    return json.dumps({"count": len(channels), "channels": channels}, ensure_ascii=False)
