"""Agent tools for semantic search over indexed filesystem directories."""
from __future__ import annotations

import json
from pathlib import Path

from app.agent.context import current_bot_id
from app.db.engine import async_session
from app.db.models import FilesystemChunk
from app.tools.registry import register

from sqlalchemy import func, select


@register({
    "type": "function",
    "function": {
        "name": "search_codebase",
        "description": (
            "Semantically search indexed filesystem directories (code, docs, configs). "
            "Returns the most relevant chunks for the query with file paths and line numbers. "
            "Use this to find functions, classes, config values, documentation, or any text "
            "in indexed directories."
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
                        "Omit to search all indexed directories for the current bot."
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
    if not bot_id:
        return json.dumps({"error": "No bot context available."})
    from app.agent.fs_indexer import retrieve_filesystem_context
    roots = [root] if root else None
    chunks, best_sim = await retrieve_filesystem_context(query, bot_id, roots=roots, top_k=top_k)
    if not chunks:
        return "No relevant results found."
    header = f"Found {len(chunks)} result(s) (best similarity: {best_sim:.3f}):\n\n"
    return header + "\n\n---\n\n".join(chunks)


@register({
    "type": "function",
    "function": {
        "name": "index_directory_now",
        "description": (
            "Trigger an immediate re-index of a filesystem directory for the current bot. "
            "Bypasses cooldown. Use after making significant file changes or to force a refresh."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the directory to re-index.",
                },
            },
            "required": ["path"],
        },
    },
})
async def index_directory_now(path: str) -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."})
    from app.agent.bots import get_bot
    try:
        bot = get_bot(bot_id)
    except Exception:
        return json.dumps({"error": f"Bot {bot_id!r} not found."})

    abs_path = str(Path(path).resolve())
    cfg = next(
        (c for c in bot.filesystem_indexes if str(Path(c.root).resolve()) == abs_path),
        None,
    )
    if cfg is None:
        return json.dumps({"error": f"Path {path!r} is not configured for bot {bot_id!r}."})

    from app.agent.fs_indexer import index_directory
    stats = await index_directory(cfg.root, bot_id, cfg.patterns, force=True)
    return json.dumps(stats)


@register({
    "type": "function",
    "function": {
        "name": "list_indexed_directories",
        "description": "List all filesystem directories indexed for the current bot, with chunk and file counts.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
})
async def list_indexed_directories() -> str:
    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."})

    async with async_session() as db:
        rows = (await db.execute(
            select(
                FilesystemChunk.root,
                func.count(FilesystemChunk.id).label("chunk_count"),
                func.count(FilesystemChunk.file_path.distinct()).label("file_count"),
                func.max(FilesystemChunk.indexed_at).label("last_indexed"),
            )
            .where(FilesystemChunk.bot_id == bot_id)
            .group_by(FilesystemChunk.root)
        )).all()

    if not rows:
        return "No directories indexed for this bot."

    lines = []
    for row in rows:
        last = row.last_indexed.strftime("%Y-%m-%d %H:%M UTC") if row.last_indexed else "never"
        lines.append(
            f"- {row.root}: {row.chunk_count} chunks across {row.file_count} files (last indexed: {last})"
        )
    return "\n".join(lines)
