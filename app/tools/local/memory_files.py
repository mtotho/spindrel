"""Local tools for file-based memory scheme: search_memory, get_memory_file, search_bot_memory."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

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
        "message": {"type": "string"},
        "error": {"type": "string"},
    },
    "required": ["count", "results"],
}


def _format_search_results(results) -> str:
    items = []
    for r in results:
        snippet = r.content
        if snippet.startswith("# "):
            first_nl = snippet.find("\n")
            if first_nl > 0:
                snippet = snippet[first_nl + 1:]
        items.append({"file_path": r.file_path, "score": round(r.score, 3), "snippet": snippet.strip()})
    return json.dumps({"count": len(items), "results": items}, ensure_ascii=False)

logger = logging.getLogger(__name__)


def _get_bot_and_root() -> tuple:
    """Resolve current bot and its workspace/memory root."""
    bot_id = current_bot_id.get()
    if not bot_id:
        return None, None, None
    from app.agent.bots import get_bot
    bot = get_bot(bot_id)
    from app.services.workspace import workspace_service
    ws_root = workspace_service.get_workspace_root(bot_id, bot)
    return bot, bot_id, ws_root


def _resolve_memory_path(name: str, memory_root: str) -> str | None:
    """Resolve a shorthand name to an absolute file path within memory/.

    Supports:
      "MEMORY" → memory/MEMORY.md
      "2026-03-25" → memory/logs/2026-03-25.md
      "deployment-guide" → memory/reference/deployment-guide.md
      "logs/2026-03-25" → memory/logs/2026-03-25.md
      "reference/foo" → memory/reference/foo.md

    Returns None if the path would escape memory/ or the file doesn't exist.
    """
    name = name.strip()
    if not name:
        return None

    # Strip .md suffix if provided
    if name.endswith(".md"):
        name = name[:-3]

    # Try direct paths first
    candidates = []

    if "/" in name:
        # Explicit subpath: memory/{name}.md
        candidates.append(os.path.join(memory_root, name + ".md"))
    else:
        # Shorthand resolution order
        # 1. MEMORY.md at root
        if name.upper() == "MEMORY":
            candidates.append(os.path.join(memory_root, "MEMORY.md"))
        # 2. Daily log (looks like a date YYYY-MM-DD)
        candidates.append(os.path.join(memory_root, "logs", name + ".md"))
        # 3. Reference doc
        candidates.append(os.path.join(memory_root, "reference", name + ".md"))
        # 4. Direct file in memory root
        candidates.append(os.path.join(memory_root, name + ".md"))

    for path in candidates:
        abs_path = os.path.realpath(path)
        # Security: ensure path stays within memory/
        if not abs_path.startswith(os.path.realpath(memory_root)):
            continue
        if os.path.isfile(abs_path):
            return abs_path

    return None


@register({
    "type": "function",
    "function": {
        "name": "search_memory",
        "description": (
            "Search your memory files using hybrid semantic + keyword search. "
            "Searches across MEMORY.md, daily logs, and reference documents. "
            "For full file contents, use get_memory_file. "
            "For workspace code/docs, use search_workspace."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (e.g. 'user preferences', 'deployment steps', 'yesterday's decisions').",
                },
            },
            "required": ["query"],
        },
    },
}, requires_bot_context=True, returns=_SEARCH_RETURNS)
async def search_memory(query: str) -> str:
    """Hybrid search across memory files."""
    bot, bot_id, ws_root = _get_bot_and_root()
    if not bot or not ws_root:
        return json.dumps({"count": 0, "results": [], "error": "Memory search is not available (no workspace context)."}, ensure_ascii=False)

    query = (query or "").strip()
    if not query:
        return json.dumps({"count": 0, "results": [], "error": "No search query provided."}, ensure_ascii=False)

    from app.services.bot_indexing import resolve_for
    from app.services.memory_scheme import get_memory_index_prefix
    from app.services.memory_search import hybrid_memory_search

    plan = resolve_for(bot, scope="workspace")
    if plan is None:
        return json.dumps({"count": 0, "results": [], "error": "Memory search requires workspace-enabled bot."}, ensure_ascii=False)
    embedding_model = plan.embedding_model
    roots = [str(Path(r).resolve()) for r in plan.roots]

    try:
        results = await hybrid_memory_search(
            query=query,
            bot_id=bot_id,
            roots=roots,
            memory_prefix=get_memory_index_prefix(bot),
            embedding_model=embedding_model,
            top_k=10,
        )
    except Exception as exc:
        logger.error("search_memory failed for bot %s: %s", bot_id, exc)
        return json.dumps({"count": 0, "results": [], "error": f"Memory search ERROR: {exc}"}, ensure_ascii=False)

    if not results:
        prefix = get_memory_index_prefix(bot)
        return json.dumps({
            "count": 0, "results": [],
            "message": f"No matching memory content found. (debug: bot={bot_id}, prefix={prefix}, model={embedding_model})",
        }, ensure_ascii=False)

    return _format_search_results(results)


@register({
    "type": "function",
    "function": {
        "name": "get_memory_file",
        "description": (
            "Read a specific memory file by name. "
            "Supports shorthand: 'MEMORY' → MEMORY.md, '2026-03-25' → logs/2026-03-25.md, "
            "'deployment-guide' → reference/deployment-guide.md. "
            "Or use explicit path: 'logs/2026-03-20', 'reference/runbook'. "
            "For searching across files, use search_memory instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "File name or path within memory/ (e.g. 'MEMORY', '2026-03-25', 'reference/deployment-guide').",
                },
            },
            "required": ["name"],
        },
    },
}, requires_bot_context=True, returns={
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "content": {"type": "string"},
        "error": {"type": "string"},
        "available": {"type": "array", "items": {"type": "string"}},
    },
})
async def get_memory_file(name: str) -> str:
    """Read a memory file by name."""
    bot, bot_id, ws_root = _get_bot_and_root()
    if not bot or not ws_root:
        return json.dumps({"error": "Memory file access is not available (no workspace context)."}, ensure_ascii=False)

    name = (name or "").strip()
    if not name:
        return json.dumps({"error": "No file name provided."}, ensure_ascii=False)

    from app.services.memory_scheme import get_memory_root
    memory_root = get_memory_root(bot, ws_root=ws_root)
    path = _resolve_memory_path(name, memory_root)

    if path is None:
        available = []
        if os.path.isdir(memory_root):
            for dirpath, _, filenames in os.walk(memory_root):
                for fn in sorted(filenames):
                    if fn.endswith(".md"):
                        rel = os.path.relpath(os.path.join(dirpath, fn), memory_root)
                        available.append(rel)
        return json.dumps({"error": f"File not found: {name}", "available": available}, ensure_ascii=False)

    try:
        content = Path(path).read_text()
        rel = os.path.relpath(path, memory_root)
        return json.dumps({"path": f"memory/{rel}", "content": content}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"Error reading file: {e}"}, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "search_bot_memory",
        "description": (
            "Search another bot's memory files (orchestrator only). "
            "Use this to look up what a specific bot knows or has recorded. "
            "Searches across their MEMORY.md, daily logs, and reference documents."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "bot_id": {
                    "type": "string",
                    "description": "The bot ID whose memory to search.",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (e.g. 'user preferences', 'deployment steps').",
                },
            },
            "required": ["bot_id", "query"],
        },
    },
}, requires_bot_context=True, returns=_SEARCH_RETURNS)
async def search_bot_memory(bot_id: str, query: str) -> str:
    """Search another bot's memory files (for orchestrators).

    Queries the target bot's own indexed chunks — each bot indexes its own
    workspace root (bots/{bot_id}/) and stores chunks under its own bot_id.
    """
    caller_bot, caller_bot_id, caller_ws_root = _get_bot_and_root()
    if not caller_bot or not caller_ws_root:
        return json.dumps({"count": 0, "results": [], "error": "search_bot_memory is not available (no workspace context)."}, ensure_ascii=False)

    if caller_bot.shared_workspace_role != "orchestrator":
        return json.dumps({"count": 0, "results": [], "error": "search_bot_memory is only available to orchestrator bots."}, ensure_ascii=False)

    target_bot_id = (bot_id or "").strip()
    query = (query or "").strip()
    if not target_bot_id:
        return json.dumps({"count": 0, "results": [], "error": "No bot_id provided."}, ensure_ascii=False)
    if not query:
        return json.dumps({"count": 0, "results": [], "error": "No search query provided."}, ensure_ascii=False)

    from app.agent.bots import get_bot
    target_bot = get_bot(target_bot_id)
    if not target_bot:
        return json.dumps({"count": 0, "results": [], "error": f"Bot not found: {target_bot_id}"}, ensure_ascii=False)
    if target_bot.memory_scheme != "workspace-files":
        return json.dumps({"count": 0, "results": [], "error": f"Bot {target_bot_id} does not use workspace-files memory scheme."}, ensure_ascii=False)

    from app.services.bot_indexing import resolve_for
    from app.services.memory_scheme import get_memory_index_prefix
    from app.services.memory_search import hybrid_memory_search

    plan = resolve_for(target_bot, scope="workspace")
    if plan is None:
        return json.dumps({"count": 0, "results": [], "error": f"Bot {target_bot_id} has workspace disabled."}, ensure_ascii=False)
    embedding_model = plan.embedding_model
    roots = [str(Path(r).resolve()) for r in plan.roots]

    try:
        results = await hybrid_memory_search(
            query=query,
            bot_id=target_bot_id,
            roots=roots,
            memory_prefix=get_memory_index_prefix(target_bot),
            embedding_model=embedding_model,
            top_k=10,
        )
    except Exception as exc:
        logger.error("search_bot_memory failed for bot %s: %s", target_bot_id, exc)
        return json.dumps({"count": 0, "results": [], "error": f"Memory search ERROR for bot {target_bot_id}: {exc}"}, ensure_ascii=False)

    if not results:
        return json.dumps({"count": 0, "results": [], "message": f"No matching memory content found for bot {target_bot_id}."}, ensure_ascii=False)

    return _format_search_results(results)
