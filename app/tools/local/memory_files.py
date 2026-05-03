"""Local tools for file-based memory scheme."""
from __future__ import annotations

import difflib
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

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


def _json_default(value: Any) -> str:
    return str(value)


def _format_search_results(results) -> str:
    items = []
    for r in results:
        snippet = r.content
        if snippet.startswith("# "):
            first_nl = snippet.find("\n")
            if first_nl > 0:
                snippet = snippet[first_nl + 1:]
        items.append({
            "file_path": r.file_path,
            "score": round(float(r.score), 3),
            "snippet": snippet.strip(),
        })
    return json.dumps({"count": len(items), "results": items}, ensure_ascii=False, default=_json_default)

logger = logging.getLogger(__name__)

_LEAKED_TOOL_CALL_RE = re.compile(
    r"(?:^|[\s{}])(?:to=functions\.|functions\.[A-Za-z_][\w.-]*|<\|tool)",
)


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
}, requires_bot_context=True, tool_metadata={
    "domains": ["memory", "repeated_lookup_tracking"],
    "capabilities": ["memory.read"],
    "exposure": "ambient",
    "auto_inject": ["workspace_files_memory"],
}, returns=_SEARCH_RETURNS)
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
}, requires_bot_context=True, tool_metadata={
    "domains": ["memory"],
    "capabilities": ["memory.read"],
    "exposure": "ambient",
    "auto_inject": ["workspace_files_memory"],
    "context_policy": {"retention": "sticky_reference"},
}, returns={
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


def _resolve_memory_write_path(path: str, memory_root: str) -> str:
    value = (path or "").strip().replace("\\", "/")
    if not value:
        raise ValueError("path is required")
    if value.startswith("memory/"):
        value = value[len("memory/"):]
    parts = [part for part in value.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        raise ValueError("path must stay inside memory")
    if not parts:
        raise ValueError("path is required")
    if not parts[-1].endswith(".md"):
        parts[-1] = parts[-1] + ".md"
    root = os.path.realpath(memory_root)
    resolved = os.path.realpath(os.path.join(root, *parts))
    if resolved != root and not resolved.startswith(root + os.sep):
        raise ValueError("path must stay inside memory")
    return resolved


def _memory_error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def _memory_text_error(*values: str | None) -> str | None:
    """Reject transcript/control syntax that should never be persisted as memory."""
    for value in values:
        if value and _LEAKED_TOOL_CALL_RE.search(value):
            return (
                "Refusing memory write: content appears to contain leaked "
                "tool-call transcript syntax. Rewrite the note as plain Markdown "
                "and call memory again."
            )
    return None


def _mimetype_for_memory_path(path: str | None) -> str:
    if path and path.lower().endswith(".md"):
        return "text/markdown"
    if path and path.lower().endswith(".json"):
        return "application/json"
    return "text/plain"


def _memory_result(
    payload: dict[str, Any],
    *,
    plain_body: str,
    body: str | dict[str, Any] | None = None,
    content_type: str = "application/json",
    display: str = "badge",
) -> str:
    rendered_body = body if body is not None else payload
    result = dict(payload)
    result["llm"] = json.dumps(payload, ensure_ascii=False, default=_json_default)
    result["_envelope"] = {
        "content_type": content_type,
        "body": rendered_body,
        "plain_body": plain_body,
        "display": display,
    }
    return json.dumps(result, ensure_ascii=False, default=_json_default)


def _memory_diff(before: str, after: str, rel_path: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/memory/{rel_path}",
        tofile=f"b/memory/{rel_path}",
        lineterm="",
    ))


def _memory_diff_stats(diff_text: str) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for line in diff_text.splitlines():
        if line.startswith(("+++ ", "--- ", "@@")):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


@register({
    "type": "function",
    "function": {
        "name": "memory",
        "description": (
            "Read and write your private bot memory files. This tool is always rooted "
            "at your bot memory directory, even when the channel is attached to a Project. "
            "Use it instead of the generic file tool for MEMORY.md, daily logs, and reference notes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["list", "read", "create", "overwrite", "append", "edit", "replace_section", "rename", "delete", "archive_older_than"],
                },
                "path": {"type": "string", "description": "Path inside memory/, e.g. MEMORY.md, logs/2026-04-29.md, reference/project.md."},
                "content": {"type": "string"},
                "find": {"type": "string"},
                "replace": {"type": "string"},
                "replace_all": {"type": "boolean"},
                "heading": {"type": "string"},
                "destination": {"type": "string"},
                "older_than_days": {"type": "integer"},
            },
            "required": ["operation"],
        },
    },
}, safety_tier="mutating", requires_bot_context=True, tool_metadata={
    "domains": ["memory"],
    "capabilities": ["memory.read", "memory.write"],
    "exposure": "ambient",
    "auto_inject": ["workspace_files_memory"],
    "context_policy": {
        "cacheable": {"arg": "action", "values": [None, "get", "list", "search", "read"], "otherwise": False}
    },
}, returns={
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "destination": {"type": "string"},
        "files": {"type": "array", "items": {"type": "string"}},
        "moved": {"type": "array", "items": {"type": "string"}},
        "skipped_fresh": {"type": "array", "items": {"type": "string"}},
        "skipped_existing": {"type": "array", "items": {"type": "string"}},
        "content": {"type": "string"},
        "message": {"type": "string"},
        "llm": {"type": "string"},
        "_envelope": {"type": "object"},
        "error": {"type": "string"},
    },
})
async def memory(
    operation: str,
    path: str | None = None,
    content: str | None = None,
    find: str | None = None,
    replace: str | None = None,
    replace_all: bool = False,
    heading: str | None = None,
    destination: str | None = None,
    older_than_days: int | None = None,
) -> str:
    bot, bot_id, ws_root = _get_bot_and_root()
    if not bot or not ws_root:
        return _memory_error("Memory file access is not available (no workspace context).")
    if getattr(bot, "memory_scheme", None) != "workspace-files":
        return _memory_error("This bot does not use workspace-files memory.")

    from app.services.memory_scheme import get_memory_root
    memory_root = get_memory_root(bot, ws_root=ws_root)
    os.makedirs(memory_root, exist_ok=True)

    operation = (operation or "").strip()
    try:
        if operation == "list":
            files: list[str] = []
            for dirpath, _, filenames in os.walk(memory_root):
                for filename in sorted(filenames):
                    if filename.endswith(".md"):
                        files.append(os.path.relpath(os.path.join(dirpath, filename), memory_root))
            return _memory_result(
                {"files": files},
                plain_body=f"Listed {len(files)} memory file(s)",
            )

        if operation == "archive_older_than":
            if not path or not destination:
                return _memory_error("path and destination are required for archive_older_than.")
            source_dir = _resolve_memory_write_path(path.rstrip("/") + "/.sentinel.md", memory_root)
            source_dir = os.path.dirname(source_dir)
            dest_dir = _resolve_memory_write_path(destination.rstrip("/") + "/.sentinel.md", memory_root)
            dest_dir = os.path.dirname(dest_dir)
            cutoff = time.time() - float(older_than_days or 0) * 86400
            moved: list[str] = []
            skipped_fresh: list[str] = []
            skipped_existing: list[str] = []
            os.makedirs(dest_dir, exist_ok=True)
            for entry in sorted(Path(source_dir).glob("*.md")) if os.path.isdir(source_dir) else []:
                if entry.stat().st_mtime > cutoff:
                    skipped_fresh.append(entry.name)
                    continue
                target = Path(dest_dir) / entry.name
                if target.exists():
                    skipped_existing.append(entry.name)
                    continue
                entry.rename(target)
                moved.append(entry.name)
            source_rel = os.path.relpath(source_dir, memory_root)
            dest_rel = os.path.relpath(dest_dir, memory_root)
            return _memory_result({
                "path": f"memory/{os.path.relpath(source_dir, memory_root)}",
                "destination": f"memory/{os.path.relpath(dest_dir, memory_root)}",
                "moved": moved,
                "skipped_fresh": skipped_fresh,
                "skipped_existing": skipped_existing,
            }, plain_body=f"Archived {len(moved)} file(s) from memory/{source_rel} to memory/{dest_rel}")

        if not path:
            return _memory_error("path is required for this operation.")
        resolved = _resolve_memory_write_path(path, memory_root)
        rel = os.path.relpath(resolved, memory_root)

        if operation == "read":
            if not os.path.isfile(resolved):
                return _memory_error(f"File not found: {rel}")
            content_text = Path(resolved).read_text()
            return _memory_result(
                {"path": f"memory/{rel}", "content": content_text},
                plain_body=f"Read memory/{rel}",
                body=content_text,
                content_type=_mimetype_for_memory_path(rel),
            )

        before_text = Path(resolved).read_text() if os.path.isfile(resolved) else ""
        if operation in {"create", "overwrite", "append", "replace_section"}:
            if error := _memory_text_error(content):
                return _memory_error(error)
        elif operation == "edit":
            if error := _memory_text_error(replace):
                return _memory_error(error)

        if operation == "create":
            if os.path.exists(resolved):
                return _memory_error(f"File already exists: {rel}")
            os.makedirs(os.path.dirname(resolved), exist_ok=True)
            Path(resolved).write_text(content or "")
        elif operation == "overwrite":
            os.makedirs(os.path.dirname(resolved), exist_ok=True)
            Path(resolved).write_text(content or "")
        elif operation == "append":
            os.makedirs(os.path.dirname(resolved), exist_ok=True)
            with open(resolved, "a", encoding="utf-8") as fh:
                fh.write(content or "")
        elif operation == "edit":
            if not os.path.isfile(resolved):
                return _memory_error(f"File not found: {rel}")
            if find is None:
                return _memory_error("find is required for edit.")
            text = Path(resolved).read_text()
            count = text.count(find)
            if count == 0:
                return _memory_error("find text not found.")
            if count > 1 and not replace_all:
                return _memory_error("find text appears multiple times; set replace_all=true.")
            Path(resolved).write_text(text.replace(find, replace or "", -1 if replace_all else 1))
        elif operation == "replace_section":
            if not heading:
                return _memory_error("heading is required for replace_section.")
            text = Path(resolved).read_text() if os.path.isfile(resolved) else ""
            marker = heading.strip()
            if not marker.startswith("#"):
                marker = "## " + marker
            pattern = re.compile(rf"(^|\n){re.escape(marker)}\n.*?(?=\n##? |\Z)", re.DOTALL)
            section = f"{marker}\n{content or ''}".rstrip() + "\n"
            if pattern.search(text):
                text = pattern.sub(lambda m: ("\n" if m.group(1) else "") + section, text, count=1)
            else:
                text = (text.rstrip() + "\n\n" + section).lstrip()
            os.makedirs(os.path.dirname(resolved), exist_ok=True)
            Path(resolved).write_text(text)
        elif operation == "rename":
            if not destination:
                return _memory_error("destination is required for rename.")
            target = _resolve_memory_write_path(destination, memory_root)
            if not os.path.isfile(resolved):
                return _memory_error(f"File not found: {rel}")
            if os.path.exists(target):
                return _memory_error(f"Destination already exists: {os.path.relpath(target, memory_root)}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.replace(resolved, target)
            rel = os.path.relpath(target, memory_root)
        elif operation == "delete":
            if not os.path.isfile(resolved):
                return _memory_error(f"File not found: {rel}")
            os.remove(resolved)
        else:
            return _memory_error(f"Unknown operation: {operation}")

        from app.services.bot_hooks import schedule_after_write
        schedule_after_write(bot_id, f"memory/{rel}")
        if operation in {"create", "overwrite", "append", "edit", "replace_section", "delete"}:
            after_text = Path(resolved).read_text() if os.path.isfile(resolved) else ""
            diff_text = _memory_diff(before_text, after_text, rel)
            if diff_text.strip():
                additions, deletions = _memory_diff_stats(diff_text)
                return _memory_result(
                    {"path": f"memory/{rel}", "message": f"{operation} complete"},
                    plain_body=(
                        f"{operation.replace('_', ' ').title()} memory/{rel}: "
                        f"+{additions} -{deletions} lines"
                    ),
                    body=diff_text,
                    content_type="application/vnd.spindrel.diff+text",
                    display="inline",
                )
        return _memory_result(
            {"path": f"memory/{rel}", "message": f"{operation} complete"},
            plain_body=f"{operation.replace('_', ' ').title()} memory/{rel}",
        )
    except Exception as exc:
        logger.exception("memory tool %s failed: %s", operation, path)
        return _memory_error(str(exc))


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
