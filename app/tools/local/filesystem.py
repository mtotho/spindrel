"""Agent tools for semantic search over indexed filesystem directories."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import delete, func, or_, select

from app.agent.context import current_bot_id, current_client_id
from app.db.engine import async_session
from app.db.models import FilesystemChunk
from app.tools.registry import register

# Scope label → (bot_id_null, client_id_null)
# Used to map a human-readable scope to which fields should be NULL.
_SCOPE_LABELS = {
    "session": "This bot in this channel (default — most specific)",
    "bot": "This bot across all channels",
    "channel": "Any bot in this channel",
    "global": "Any bot in any channel",
}


def _resolve_scope(scope: str, bot_id: str | None, client_id: str | None) -> tuple[str | None, str | None]:
    """Map scope name to (resolved_bot_id, resolved_client_id) for indexing/deletion."""
    if scope == "session":
        return bot_id, client_id
    elif scope == "bot":
        return bot_id, None
    elif scope == "channel":
        return None, client_id
    elif scope == "global":
        return None, None
    return bot_id, client_id  # default fallback


@register({
    "type": "function",
    "function": {
        "name": "search_codebase",
        "description": (
            "Semantically search indexed filesystem directories (code, docs, configs). "
            "Returns the most relevant chunks for the query with file paths and line numbers. "
            "Use this to find functions, classes, config values, documentation, or any text "
            "in indexed directories. Searches across all scopes visible to the current bot and channel."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query.",
                },
                "root": {
                    "type": "string",
                    "description": (
                        "Optional. Absolute path of a specific indexed root to restrict search to. "
                        "Omit to search all indexed directories visible to this bot."
                    ),
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
async def search_codebase(
    query: str,
    root: str | None = None,
    top_k: int | None = None,
) -> str:
    bot_id = current_bot_id.get()
    client_id = current_client_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."})
    from app.agent.fs_indexer import retrieve_filesystem_context
    roots = [root] if root else None
    chunks, best_sim = await retrieve_filesystem_context(
        query, bot_id, client_id=client_id, roots=roots, top_k=top_k
    )
    if not chunks:
        return "No relevant results found."
    header = f"Found {len(chunks)} result(s) (best similarity: {best_sim:.3f}):\n\n"
    return header + "\n\n---\n\n".join(chunks)


@register({
    "type": "function",
    "function": {
        "name": "index_directory_now",
        "description": (
            "Trigger an immediate re-index of a filesystem directory. "
            "Bypasses cooldown. Use after making significant file changes or to force a refresh. "
            "Scope controls who can search the indexed content: "
            "'session' (default) = this bot in this channel, "
            "'bot' = this bot across all channels, "
            "'channel' = any bot in this channel, "
            "'global' = any bot in any channel."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the directory to re-index.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["session", "bot", "channel", "global"],
                    "description": (
                        "Who can search this index. "
                        "'session' = this bot in this channel (default), "
                        "'bot' = this bot across all channels, "
                        "'channel' = any bot in this channel, "
                        "'global' = any bot in any channel."
                    ),
                },
            },
            "required": ["path"],
        },
    },
})
async def index_directory_now(path: str, scope: str = "session") -> str:
    bot_id = current_bot_id.get()
    client_id = current_client_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."})

    resolved_bot_id, resolved_client_id = _resolve_scope(scope, bot_id, client_id)

    # Find patterns from bot config if this path is pre-configured
    from app.agent.bots import get_bot
    patterns = ["**/*.py", "**/*.md", "**/*.yaml"]
    try:
        bot = get_bot(bot_id)
        abs_path = str(Path(path).resolve())
        cfg = next(
            (c for c in bot.filesystem_indexes if str(Path(c.root).resolve()) == abs_path),
            None,
        )
        if cfg is not None:
            patterns = cfg.patterns
    except Exception:
        pass

    from app.agent.fs_indexer import index_directory
    stats = await index_directory(
        path, resolved_bot_id, patterns,
        client_id=resolved_client_id,
        force=True,
    )
    stats["scope"] = scope
    return json.dumps(stats)


@register({
    "type": "function",
    "function": {
        "name": "list_indexed_directories",
        "description": "List all filesystem directories indexed that are visible to the current bot and channel, with chunk and file counts.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
})
async def list_indexed_directories() -> str:
    bot_id = current_bot_id.get()
    client_id = current_client_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."})

    bot_filter = or_(FilesystemChunk.bot_id == bot_id, FilesystemChunk.bot_id.is_(None))
    client_filter = (
        or_(FilesystemChunk.client_id == client_id, FilesystemChunk.client_id.is_(None))
        if client_id is not None
        else FilesystemChunk.client_id.is_(None)
    )

    async with async_session() as db:
        rows = (await db.execute(
            select(
                FilesystemChunk.root,
                FilesystemChunk.bot_id,
                FilesystemChunk.client_id,
                func.count(FilesystemChunk.id).label("chunk_count"),
                func.count(FilesystemChunk.file_path.distinct()).label("file_count"),
                func.max(FilesystemChunk.indexed_at).label("last_indexed"),
            )
            .where(bot_filter, client_filter)
            .group_by(FilesystemChunk.root, FilesystemChunk.bot_id, FilesystemChunk.client_id)
        )).all()

    if not rows:
        return "No directories indexed visible to this bot."

    lines = []
    for row in rows:
        last = row.last_indexed.strftime("%Y-%m-%d %H:%M UTC") if row.last_indexed else "never"
        scope_label = _scope_label(row.bot_id, row.client_id, bot_id, client_id)
        lines.append(
            f"- {row.root} [{scope_label}]: {row.chunk_count} chunks across {row.file_count} files (last indexed: {last})"
        )
    return "\n".join(lines)


@register({
    "type": "function",
    "function": {
        "name": "delete_filesystem_index",
        "description": (
            "Delete all indexed chunks for a filesystem directory at the specified scope. "
            "The bot must own the index at that scope (cannot delete another bot's or channel's index). "
            "Use 'session' to delete only this bot+channel's index, 'bot' to delete this bot's "
            "cross-channel index, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path of the indexed directory root to delete.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["session", "bot", "channel", "global"],
                    "description": (
                        "Scope of the index to delete. Must match the scope it was indexed with. "
                        "'session' = this bot in this channel, "
                        "'bot' = this bot across all channels, "
                        "'channel' = any bot in this channel, "
                        "'global' = any bot in any channel."
                    ),
                },
            },
            "required": ["path", "scope"],
        },
    },
})
async def delete_filesystem_index(path: str, scope: str = "session") -> str:
    bot_id = current_bot_id.get()
    client_id = current_client_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."})

    resolved_bot_id, resolved_client_id = _resolve_scope(scope, bot_id, client_id)
    abs_root = str(Path(path).resolve())

    conds = [FilesystemChunk.root == abs_root]
    if resolved_bot_id is None:
        conds.append(FilesystemChunk.bot_id.is_(None))
    else:
        conds.append(FilesystemChunk.bot_id == resolved_bot_id)
    if resolved_client_id is None:
        conds.append(FilesystemChunk.client_id.is_(None))
    else:
        conds.append(FilesystemChunk.client_id == resolved_client_id)

    async with async_session() as db:
        result = await db.execute(delete(FilesystemChunk).where(*conds))
        await db.commit()

    return json.dumps({"deleted_chunks": result.rowcount, "root": abs_root, "scope": scope})


def _scope_label(row_bot_id: str | None, row_client_id: str | None, current_bot: str, current_client: str | None) -> str:
    """Human-readable scope description for list output."""
    if row_bot_id is None and row_client_id is None:
        return "global"
    if row_bot_id is None:
        return f"channel:{row_client_id}"
    if row_client_id is None:
        return f"bot:{row_bot_id}"
    return f"session:{row_bot_id}/{row_client_id}"
