"""Local tools for channel workspace: search_channel_archive, search_channel_workspace, list_channels."""
from __future__ import annotations

import json
import logging
import uuid
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


async def _get_bot_and_roots(channel_id: str | None = None, *, source_tool: str = "search_channel_workspace") -> tuple:
    """Resolve bot, channel_id, workspace root, and embedding model.

    Channel WorkSurface access is participant-based: the primary bot and
    ChannelBotMember rows may search the channel. Member access resolves using
    the owning bot's workspace root so search hits the correct directory.
    """
    bot_id = current_bot_id.get()
    ch_id = channel_id or (str(current_channel_id.get()) if current_channel_id.get() else None)
    if not bot_id or not ch_id:
        return None, None, None, None, None, "Channel workspace search is not available (no channel workspace context)."

    from app.agent.bots import get_bot
    bot = get_bot(bot_id)
    if not bot or not bot.workspace.enabled:
        return None, None, None, None, None, "Channel workspace search is not available (no workspace context)."

    try:
        target_channel_id = uuid.UUID(str(ch_id))
    except (TypeError, ValueError):
        return bot, ch_id, None, None, None, f"Unknown channel: {ch_id}"

    from app.db.engine import async_session as _async_session
    from app.db.models import Channel
    from app.services.projects import resolve_channel_work_surface
    from app.services.worksurface_access import (
        authorize_channel_worksurface,
        record_worksurface_boundary_event,
    )
    from app.services.bot_indexing import resolve_for
    from app.services.channel_workspace import _get_ws_root

    effective_bot = bot
    surface = None
    try:
        async with _async_session() as db:
            decision = await authorize_channel_worksurface(
                db,
                actor_bot_id=bot_id,
                channel_id=target_channel_id,
            )
            should_trace = (
                bool(channel_id)
                or decision.reason == "member"
                or not decision.allowed
            )
            if should_trace:
                await record_worksurface_boundary_event(
                    decision,
                    mode="search",
                    source_tool=source_tool,
                )
            if not decision.allowed:
                return bot, ch_id, None, None, None, decision.error

            if decision.owner_bot_id and decision.owner_bot_id != bot_id:
                owner_bot = get_bot(decision.owner_bot_id)
                if not owner_bot or not owner_bot.workspace.enabled:
                    return bot, ch_id, None, None, None, "Access denied: channel owner workspace is not available."
                effective_bot = owner_bot

            channel = await db.get(Channel, target_channel_id)
            if channel is not None:
                surface = await resolve_channel_work_surface(db, channel, effective_bot)
    except Exception:
        logger.debug("Could not resolve work surface access for channel %s", ch_id, exc_info=True)
        return bot, ch_id, None, None, None, "Channel workspace search is not available (access check failed)."

    ws_root = str(Path(_get_ws_root(effective_bot)).resolve())
    plan = resolve_for(effective_bot, scope="workspace")
    embedding_model = plan.embedding_model if plan is not None else None
    return bot, ch_id, ws_root, embedding_model, surface, None


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
    bot, ch_id, ws_root, embedding_model, _surface, access_error = await _get_bot_and_roots(source_tool="search_channel_archive")
    if not bot or not ch_id:
        return json.dumps({"count": 0, "results": [], "error": "Archive search is not available (no channel workspace context)."}, ensure_ascii=False)
    if access_error:
        return json.dumps({"count": 0, "results": [], "error": access_error}, ensure_ascii=False)

    query = (query or "").strip()
    if not query:
        return json.dumps({"count": 0, "results": [], "error": "No search query provided."}, ensure_ascii=False)

    from app.services.channel_workspace import get_channel_workspace_index_prefix
    from app.services.bot_indexing import channel_index_bot_id
    from app.services.memory_search import hybrid_memory_search

    sentinel = channel_index_bot_id(ch_id)
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
        from app.services.bot_indexing import reindex_channel
        asyncio.create_task(reindex_channel(ch_id, bot))
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
    bot, ch_id, ws_root, embedding_model, surface, access_error = await _get_bot_and_roots(
        channel_id,
        source_tool="search_channel_workspace",
    )
    if not bot or not ch_id:
        return json.dumps({"count": 0, "results": [], "error": "Channel workspace search is not available (no workspace context)."}, ensure_ascii=False)
    if access_error:
        return json.dumps({"count": 0, "results": [], "error": access_error}, ensure_ascii=False)

    query = (query or "").strip()
    if not query:
        return json.dumps({"count": 0, "results": [], "error": "No search query provided."}, ensure_ascii=False)

    from app.services.bot_indexing import channel_index_bot_id
    from app.services.memory_search import hybrid_memory_search

    sentinel = channel_index_bot_id(ch_id)
    prefix = surface.index_prefix if surface is not None else f"channels/{ch_id}"
    roots = [surface.index_root_host_path] if surface is not None else [ws_root]

    try:
        results = await hybrid_memory_search(
            query=query,
            bot_id=sentinel,
            roots=roots,
            memory_prefix=prefix,
            embedding_model=embedding_model,
            top_k=10,
        )
    except Exception as exc:
        logger.error("search_channel_workspace failed for channel %s: %s", ch_id, exc)
        return json.dumps({"count": 0, "results": [], "error": f"Channel workspace search ERROR: {exc}"}, ensure_ascii=False)

    if not results:
        import asyncio
        from app.services.bot_indexing import reindex_channel
        asyncio.create_task(reindex_channel(ch_id, bot))
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
    bot, ch_id, ws_root, embedding_model, surface, access_error = await _get_bot_and_roots(source_tool="search_channel_knowledge")
    if not bot or not ch_id:
        return json.dumps({"count": 0, "results": [], "error": "Channel knowledge search is not available (no channel workspace context)."}, ensure_ascii=False)
    if access_error:
        return json.dumps({"count": 0, "results": [], "error": access_error}, ensure_ascii=False)

    query = (query or "").strip()
    if not query:
        return json.dumps({"count": 0, "results": [], "error": "No search query provided."}, ensure_ascii=False)

    from app.services.bot_indexing import channel_index_bot_id
    from app.services.memory_search import hybrid_memory_search

    sentinel = channel_index_bot_id(ch_id)
    prefix = surface.knowledge_index_prefix if surface is not None else f"channels/{ch_id}/knowledge-base"
    roots = [surface.index_root_host_path] if surface is not None else [ws_root]

    try:
        results = await hybrid_memory_search(
            query=query,
            bot_id=sentinel,
            roots=roots,
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

    from app.db.engine import async_session
    from sqlalchemy import select
    from app.db.models import Channel

    async with async_session() as db:
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
        entry["is_member"] = str(row.bot_id) != bot_id
        channels.append(entry)

    return json.dumps({"count": len(channels), "channels": channels}, ensure_ascii=False)
