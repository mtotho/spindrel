"""Local tools for file-based memory scheme: search_memory, get_memory_file, search_bot_memory."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from app.agent.context import current_bot_id
from app.tools.registry import register

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
            "Searches across MEMORY.md, all daily logs, and reference documents. "
            "Returns matching chunks with file path and relevance score."
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
})
async def search_memory(query: str) -> str:
    """Hybrid search across memory files."""
    bot, bot_id, ws_root = _get_bot_and_root()
    if not bot or not ws_root:
        return "Memory search is not available (no workspace context)."

    query = (query or "").strip()
    if not query:
        return "No search query provided."

    from app.services.memory_scheme import get_memory_index_prefix
    from app.services.memory_search import hybrid_memory_search
    from app.services.workspace_indexing import resolve_indexing, get_all_roots

    # Use the RESOLVED embedding model (same as FS_CONTEXT / indexer) — not the bare default
    _resolved = resolve_indexing(bot.workspace.indexing, bot._workspace_raw, bot._ws_indexing_config)
    embedding_model = _resolved["embedding_model"]

    # Search all roots; use index-aware prefix (bots/{id}/memory for shared workspace)
    roots = [str(Path(r).resolve()) for r in get_all_roots(bot)]

    results = await hybrid_memory_search(
        query=query,
        bot_id=bot_id,
        roots=roots,
        memory_prefix=get_memory_index_prefix(bot),
        embedding_model=embedding_model,
        top_k=10,
    )

    if not results:
        # Include diagnostic info to help debug — check server logs for details
        prefix = get_memory_index_prefix(bot)
        return (
            f"No matching memory content found.\n"
            f"(debug: bot={bot_id}, roots={roots}, prefix={prefix}, model={embedding_model})\n"
            f"Check server logs for MEMORY SEARCH DIAGNOSTIC."
        )

    lines = []
    for r in results:
        # Strip the file header line (e.g. "# memory/logs/2026-03-28.md")
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
        "name": "get_memory_file",
        "description": (
            "Read a specific memory file by name. "
            "Supports shorthand: 'MEMORY' → MEMORY.md, '2026-03-25' → logs/2026-03-25.md, "
            "'deployment-guide' → reference/deployment-guide.md. "
            "Or use explicit path: 'logs/2026-03-20', 'reference/runbook'."
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
})
async def get_memory_file(name: str) -> str:
    """Read a memory file by name."""
    bot, bot_id, ws_root = _get_bot_and_root()
    if not bot or not ws_root:
        return "Memory file access is not available (no workspace context)."

    name = (name or "").strip()
    if not name:
        return "No file name provided."

    from app.services.memory_scheme import get_memory_root
    memory_root = get_memory_root(bot, ws_root=ws_root)
    path = _resolve_memory_path(name, memory_root)

    if path is None:
        # List available files to help the bot
        available = []
        if os.path.isdir(memory_root):
            for dirpath, _, filenames in os.walk(memory_root):
                for fn in sorted(filenames):
                    if fn.endswith(".md"):
                        rel = os.path.relpath(os.path.join(dirpath, fn), memory_root)
                        available.append(rel)
        if available:
            return f"File not found: {name}\nAvailable memory files:\n" + "\n".join(f"  - {f}" for f in available)
        return f"File not found: {name} (memory directory is empty)"

    try:
        content = Path(path).read_text()
        rel = os.path.relpath(path, memory_root)
        return f"# memory/{rel}\n\n{content}"
    except Exception as e:
        return f"Error reading file: {e}"


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
})
async def search_bot_memory(bot_id: str, query: str) -> str:
    """Search another bot's memory files (for orchestrators).

    Queries the target bot's own indexed chunks — each bot indexes its own
    workspace root (bots/{bot_id}/) and stores chunks under its own bot_id.
    """
    caller_bot, caller_bot_id, caller_ws_root = _get_bot_and_root()
    if not caller_bot or not caller_ws_root:
        return "search_bot_memory is not available (no workspace context)."

    # Gate: only orchestrators can search other bots' memory
    if not (caller_bot.shared_workspace_id and caller_bot.shared_workspace_role == "orchestrator"):
        return "search_bot_memory is only available to orchestrator bots."

    target_bot_id = (bot_id or "").strip()
    query = (query or "").strip()
    if not target_bot_id:
        return "No bot_id provided."
    if not query:
        return "No search query provided."

    from app.agent.bots import get_bot
    target_bot = get_bot(target_bot_id)
    if not target_bot:
        return f"Bot not found: {target_bot_id}"
    if target_bot.memory_scheme != "workspace-files":
        return f"Bot {target_bot_id} does not use workspace-files memory scheme."

    # Each bot indexes its own workspace root and stores chunks under its own
    # bot_id. Query the target's chunks directly.
    from app.services.memory_search import hybrid_memory_search
    from app.services.memory_scheme import get_memory_index_prefix
    from app.services.workspace_indexing import resolve_indexing, get_all_roots

    # Use the target bot's resolved embedding model
    _resolved = resolve_indexing(
        target_bot.workspace.indexing, target_bot._workspace_raw, target_bot._ws_indexing_config,
    )
    embedding_model = _resolved["embedding_model"]

    roots = [str(Path(r).resolve()) for r in get_all_roots(target_bot)]

    results = await hybrid_memory_search(
        query=query,
        bot_id=target_bot_id,
        roots=roots,
        memory_prefix=get_memory_index_prefix(target_bot),
        embedding_model=embedding_model,
        top_k=10,
    )

    if not results:
        return f"No matching memory content found for bot {target_bot_id}."

    lines = [f"**Memory search results for bot `{target_bot_id}`:**\n"]
    for r in results:
        content = r.content
        if content.startswith("# "):
            first_nl = content.find("\n")
            if first_nl > 0:
                content = content[first_nl + 1:]
        lines.append(f"**{r.file_path}** (score: {r.score:.3f})\n{content.strip()}")

    return "\n\n---\n\n".join(lines)
