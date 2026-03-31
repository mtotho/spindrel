"""file — direct file operations inside the bot's workspace.

Bypasses shell entirely, avoiding quoting/escaping issues with exec_command.
Operations: read, write, append, edit, list, delete, mkdir.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from app.agent.context import current_bot_id
from app.tools.registry import register

logger = logging.getLogger(__name__)

MAX_CONTENT_BYTES = 1_048_576  # 1 MB
MAX_READ_LINES = 2000
DEFAULT_READ_LINES = 500

_CHANNEL_PATH_RE = re.compile(r"^/workspace/channels/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:/|$)")


def _get_bot_and_workspace_root() -> tuple:
    """Resolve current bot and workspace root. Returns (bot, bot_id, ws_root) or Nones."""
    bot_id = current_bot_id.get()
    if not bot_id:
        return None, None, None
    from app.agent.bots import get_bot
    bot = get_bot(bot_id)
    from app.services.workspace import workspace_service
    ws_root = workspace_service.get_workspace_root(bot_id, bot)
    return bot, bot_id, ws_root


def _resolve_path(path: str, ws_root: str, bot=None) -> str:
    """Resolve a path to an absolute host-side path within the workspace.

    Handles:
    - /workspace/... container paths (translated via workspace_service)
    - Relative paths (joined with bot workspace root)
    - Absolute paths (verified to be within allowed boundaries)

    For shared workspace bots the boundary is the entire shared workspace root,
    but access to other bots' private directories is blocked.  For standalone
    bots the boundary is the bot's own workspace root (which contains channels/).

    Raises ValueError on path traversal or access violation.
    """
    path = path.strip()
    if not path:
        raise ValueError("Empty path.")

    from app.services.workspace import workspace_service

    # Determine shared workspace root (if applicable)
    shared_root: str | None = None
    if bot and bot.shared_workspace_id:
        from app.services.shared_workspace import shared_workspace_service
        shared_root = os.path.realpath(
            shared_workspace_service.get_host_root(bot.shared_workspace_id)
        )

    # Translate container-style /workspace/... paths
    if path.startswith("/workspace/") or path == "/workspace":
        if bot and (bot.workspace.type == "docker" or bot.shared_workspace_id):
            path = workspace_service.translate_path(
                bot.id, path, bot.workspace, bot=bot,
            )
        else:
            # Host workspace — strip /workspace/ prefix and join with root
            rel = path[len("/workspace/"):] if path.startswith("/workspace/") else ""
            path = os.path.join(ws_root, rel)

    # Relative paths: join with bot workspace root (bots/{bot_id}/ for shared,
    # or {base}/{bot_id}/ for standalone).  This means memory/MEMORY.md always
    # resolves to the bot's own directory.
    if not os.path.isabs(path):
        path = os.path.join(ws_root, path)

    # Resolve symlinks and ..
    resolved = os.path.realpath(path)
    ws_real = os.path.realpath(ws_root)

    if shared_root:
        # --- Shared workspace bot ---
        # Outer boundary: must stay within the shared workspace root.
        if not (resolved == shared_root or resolved.startswith(shared_root + os.sep)):
            raise ValueError(f"Path escapes workspace: {path}")
        # Inner boundary: block access to other bots' private directories.
        bots_dir = os.path.join(shared_root, "bots")
        if resolved.startswith(bots_dir + os.sep):
            own_bot_dir = os.path.realpath(os.path.join(bots_dir, bot.id))
            if not (resolved == own_bot_dir or resolved.startswith(own_bot_dir + os.sep)):
                raise ValueError(f"Cannot access another bot's directory: {path}")
    else:
        # --- Standalone bot ---
        # Boundary: must stay within the bot's own workspace root.
        if not (resolved == ws_real or resolved.startswith(ws_real + os.sep)):
            raise ValueError(f"Path escapes workspace: {path}")

    return resolved


async def _maybe_resolve_cross_channel(path: str, bot, ws_root: str):
    """If *path* targets another bot's channel and caller has cross_workspace_access,
    return (effective_ws_root, effective_bot).  Otherwise return (ws_root, bot).
    """
    if not bot.cross_workspace_access:
        return ws_root, bot

    m = _CHANNEL_PATH_RE.match(path.strip())
    if not m:
        return ws_root, bot

    channel_id = m.group(1)

    from app.tools.local.channel_workspace import _resolve_channel_owner_bot
    owner_bot = await _resolve_channel_owner_bot(channel_id, bot.id)

    if owner_bot is None:
        # Same bot or couldn't resolve — use caller's workspace
        return ws_root, bot

    from app.services.channel_workspace import _get_ws_root
    owner_ws_root = _get_ws_root(owner_bot)
    return owner_ws_root, owner_bot


def _error(msg: str) -> str:
    return json.dumps({"error": msg})


@register({
    "type": "function",
    "function": {
        "name": "file",
        "description": (
            "Direct file operations inside your workspace. Bypasses shell — "
            "no quoting issues with apostrophes, backticks, or special characters. "
            "Operations: read, write, append, edit, list, delete, mkdir."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["read", "write", "append", "edit", "list", "delete", "mkdir"],
                    "description": "The file operation to perform.",
                },
                "path": {
                    "type": "string",
                    "description": (
                        "File or directory path. Relative paths resolve from workspace root. "
                        "Container paths (/workspace/...) are translated automatically."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "File content (for write/append operations).",
                },
                "find": {
                    "type": "string",
                    "description": "Exact string to find (for edit operation).",
                },
                "replace": {
                    "type": "string",
                    "description": "Replacement string (for edit operation).",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences (for edit). Default: false (first only).",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line offset for read (1-based, default: 1).",
                },
                "limit": {
                    "type": "integer",
                    "description": f"Max lines to return for read (default: {DEFAULT_READ_LINES}, max: {MAX_READ_LINES}).",
                },
            },
            "required": ["operation", "path"],
        },
    },
})
async def file(
    operation: str,
    path: str,
    content: str | None = None,
    find: str | None = None,
    replace: str | None = None,
    replace_all: bool = False,
    offset: int | None = None,
    limit: int | None = None,
) -> str:
    """Dispatch file operations."""
    bot, bot_id, ws_root = _get_bot_and_workspace_root()
    if not bot:
        return _error("No bot context available.")
    if not ws_root:
        return _error("No workspace configured for this bot.")

    # Cross-workspace channel access: if the path targets another bot's
    # channel and we have cross_workspace_access, switch to that bot's
    # workspace root so the path resolves correctly.
    effective_ws_root, effective_bot = await _maybe_resolve_cross_channel(
        path, bot, ws_root,
    )

    try:
        resolved = _resolve_path(path, effective_ws_root, effective_bot)
    except ValueError as e:
        return _error(str(e))

    try:
        if operation == "read":
            return _op_read(resolved, effective_ws_root, offset, limit)
        elif operation == "write":
            return _op_write(resolved, content)
        elif operation == "append":
            return _op_append(resolved, content)
        elif operation == "edit":
            return _op_edit(resolved, find, replace, replace_all)
        elif operation == "list":
            return _op_list(resolved, effective_ws_root)
        elif operation == "delete":
            return _op_delete(resolved)
        elif operation == "mkdir":
            return _op_mkdir(resolved)
        else:
            return _error(f"Unknown operation: {operation}")
    except Exception as exc:
        logger.exception("file tool %s failed: %s", operation, path)
        return _error(f"{operation} failed: {exc}")


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


def _op_read(path: str, ws_root: str, offset: int | None, limit: int | None) -> str:
    if not os.path.isfile(path):
        return _error(f"File not found: {os.path.relpath(path, os.path.realpath(ws_root))}")

    lines = Path(path).read_text().splitlines(keepends=True)
    total = len(lines)

    off = max(1, offset or 1)
    lim = min(limit or DEFAULT_READ_LINES, MAX_READ_LINES)

    selected = lines[off - 1 : off - 1 + lim]
    numbered = []
    for i, line in enumerate(selected, start=off):
        numbered.append(f"{i:>6}\t{line.rstrip()}")

    rel = os.path.relpath(path, os.path.realpath(ws_root))
    header = f"# {rel} ({total} lines)"
    if off > 1 or off - 1 + lim < total:
        header += f" [showing {off}-{min(off - 1 + lim, total)}]"

    return header + "\n" + "\n".join(numbered)


def _op_write(path: str, content: str | None) -> str:
    if content is None:
        return _error("content is required for write.")
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        return _error(f"Content exceeds {MAX_CONTENT_BYTES} byte limit.")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    Path(path).write_text(content)
    size = os.path.getsize(path)
    return json.dumps({"ok": True, "bytes": size})


def _op_append(path: str, content: str | None) -> str:
    if content is None:
        return _error("content is required for append.")
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        return _error(f"Content exceeds {MAX_CONTENT_BYTES} byte limit.")

    os.makedirs(os.path.dirname(path), exist_ok=True)

    # If file exists and doesn't end with newline, prepend one
    prefix = ""
    if os.path.isfile(path):
        with open(path, "rb") as f:
            f.seek(0, 2)  # end
            if f.tell() > 0:
                f.seek(-1, 2)
                if f.read(1) != b"\n":
                    prefix = "\n"

    with open(path, "a") as f:
        f.write(prefix + content)

    size = os.path.getsize(path)
    return json.dumps({"ok": True, "bytes": size})


def _op_edit(path: str, find: str | None, replace: str | None, replace_all: bool) -> str:
    if find is None:
        return _error("find is required for edit.")
    if replace is None:
        return _error("replace is required for edit.")
    if not os.path.isfile(path):
        return _error("File not found.")

    text = Path(path).read_text()

    if find not in text:
        # Provide a hint: show a snippet around closest partial match
        hint = ""
        find_stripped = find.strip()
        if find_stripped and find_stripped in text:
            hint = " Hint: the text exists but with different leading/trailing whitespace. Try with exact whitespace."
        return _error(f"find string not found in file.{hint}")

    if replace_all:
        count = text.count(find)
        new_text = text.replace(find, replace)
    else:
        count = 1
        new_text = text.replace(find, replace, 1)

    Path(path).write_text(new_text)
    return json.dumps({"ok": True, "replacements": count})


def _op_list(path: str, ws_root: str) -> str:
    if not os.path.isdir(path):
        return _error("Not a directory.")

    entries = []
    try:
        items = sorted(os.listdir(path))
    except PermissionError:
        return _error("Permission denied.")

    dirs_first = sorted(items, key=lambda x: (not os.path.isdir(os.path.join(path, x)), x))

    for name in dirs_first:
        full = os.path.join(path, name)
        if os.path.isdir(full):
            entries.append({"name": name, "type": "dir"})
        else:
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            entries.append({"name": name, "type": "file", "size": size})

    rel = os.path.relpath(path, os.path.realpath(ws_root))
    return json.dumps({"path": rel, "entries": entries})


def _op_delete(path: str) -> str:
    if os.path.isdir(path):
        return _error("Cannot delete directories. Use exec_command with 'rm -r' for that.")
    if not os.path.exists(path):
        return _error("File not found.")

    os.remove(path)
    return json.dumps({"ok": True, "deleted": True})


def _op_mkdir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return json.dumps({"ok": True, "created": True})
