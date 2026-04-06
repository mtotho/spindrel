"""Local tools for channel workspace: search_channel_archive, search_channel_workspace, list_workspace_channels."""
from __future__ import annotations

import logging
from pathlib import Path

from app.agent.context import current_bot_id, current_channel_id
from app.tools.registry import register

logger = logging.getLogger(__name__)


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

    from app.services.channel_workspace import _get_ws_root
    from app.services.workspace_indexing import resolve_indexing

    ws_root = str(Path(_get_ws_root(effective_bot)).resolve())
    _resolved = resolve_indexing(
        effective_bot.workspace.indexing,
        effective_bot._workspace_raw,
        effective_bot._ws_indexing_config,
    )
    embedding_model = _resolved["embedding_model"]
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
            "Returns matching chunks with file paths and relevance scores."
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
})
async def search_channel_archive(query: str) -> str:
    """Search archived workspace files for the current channel."""
    bot, ch_id, ws_root, embedding_model = await _get_bot_and_roots()
    if not bot or not ch_id:
        return "Archive search is not available (no channel workspace context)."

    query = (query or "").strip()
    if not query:
        return "No search query provided."

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
        return f"Archive search ERROR: {exc}"

    if not results:
        # Trigger background re-index in case files were written via exec_command
        import asyncio
        from app.services.channel_workspace_indexing import index_channel_workspace
        asyncio.create_task(index_channel_workspace(ch_id, bot))
        return "No matching archived content found."

    lines = []
    for r in results:
        content = r.content
        if content.startswith("# "):
            first_nl = content.find("\n")
            if first_nl > 0:
                content = content[first_nl + 1:]
        lines.append(f"**{r.file_path}** (score: {r.score:.3f})\n{content.strip()}")

    return "\n\n---\n\n".join(lines)


@register({
    "type": "function",
    "function": {
        "name": "search_channel_workspace",
        "description": (
            "Search a channel's workspace files (both active and archived). "
            "If no channel_id is provided, searches the current channel. "
            "Useful for finding information across active workspace files and archives."
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
})
async def search_channel_workspace(query: str, channel_id: str | None = None) -> str:
    """Search channel workspace files (active + archive)."""
    bot, ch_id, ws_root, embedding_model = await _get_bot_and_roots(channel_id)
    if not bot or not ch_id:
        return "Channel workspace search is not available (no workspace context)."

    query = (query or "").strip()
    if not query:
        return "No search query provided."

    from app.services.channel_workspace import get_channel_workspace_index_prefix
    from app.services.channel_workspace_indexing import _get_channel_index_bot_id
    from app.services.memory_search import hybrid_memory_search

    sentinel = _get_channel_index_bot_id(ch_id)
    # Search both active + archive (the whole workspace prefix)
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
        return f"Channel workspace search ERROR: {exc}"

    if not results:
        return "No matching workspace content found."

    lines = []
    for r in results:
        content = r.content
        if content.startswith("# "):
            first_nl = content.find("\n")
            if first_nl > 0:
                content = content[first_nl + 1:]
        lines.append(f"**{r.file_path}** (score: {r.score:.3f})\n{content.strip()}")

    return "\n\n---\n\n".join(lines)


@register({
    "type": "function",
    "function": {
        "name": "list_workspace_channels",
        "description": (
            "List other channels that have workspace enabled. "
            "Returns channel IDs and display names so you can use search_channel_workspace "
            "to search their files. Useful when the user references another project or channel."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
})
async def list_workspace_channels() -> str:
    """List channels with workspace enabled for cross-channel discovery."""
    bot_id = current_bot_id.get()
    my_ch_id = str(current_channel_id.get()) if current_channel_id.get() else None
    if not bot_id:
        return "Not available (no bot context)."

    from app.agent.bots import get_bot
    bot = get_bot(bot_id)
    cross_access = bot.cross_workspace_access if bot else False

    from app.db.engine import async_session
    from sqlalchemy import select, true
    from app.db.models import Bot as BotRow, Channel

    async with async_session() as db:
        if cross_access:
            # Cross-workspace: list channels across ALL bots, include bot name
            stmt = (
                select(Channel.id, Channel.name, Channel.client_id, Channel.bot_id, BotRow.name.label("bot_name"))
                .join(BotRow, BotRow.id == Channel.bot_id)
                .where(Channel.channel_workspace_enabled == true())
                .order_by(BotRow.name, Channel.name)
            )
        else:
            from app.services.channels import bot_channel_filter
            stmt = (
                select(Channel.id, Channel.name, Channel.client_id, Channel.bot_id)
                .where(bot_channel_filter(bot_id))
                .where(Channel.channel_workspace_enabled == true())
                .order_by(Channel.name)
            )
        rows = (await db.execute(stmt)).all()

    if not rows:
        return "No channels with workspace enabled found."

    lines = []
    for row in rows:
        ch_str = str(row.id)
        label = row.name or row.client_id
        marker = " (current)" if ch_str == my_ch_id else ""
        if cross_access:
            bot_label = row.bot_name or str(row.bot_id)
            own = " (yours)" if str(row.bot_id) == bot_id else ""
            lines.append(f"- **{label}**{marker} [{bot_label}{own}]: `{ch_str}`")
        else:
            role = " (member)" if str(row.bot_id) != bot_id else ""
            lines.append(f"- **{label}**{marker}{role}: `{ch_str}`")

    return "Channels with workspace enabled:\n" + "\n".join(lines)
