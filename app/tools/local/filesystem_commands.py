"""Host filesystem tools — read, write, list, and find files using pathlib."""
import json
import os
from pathlib import Path

from app.agent.bots import FilesystemAccessEntry, get_bot
from app.agent.context import current_bot_id
from app.config import settings
from app.tools.registry import register


def _resolve_and_check(
    path: str,
    fs_access: list[FilesystemAccessEntry],
    require_write: bool = False,
) -> Path:
    """Resolve path to realpath and verify it is within an allowed access entry."""
    real = Path(os.path.realpath(path))

    if not fs_access:
        raise PermissionError("No filesystem access configured for this bot.")

    for entry in fs_access:
        entry_real = Path(os.path.realpath(entry.path))
        if real == entry_real or str(real).startswith(str(entry_real).rstrip("/") + "/"):
            if require_write and entry.mode not in ("write", "readwrite"):
                raise PermissionError(
                    f"Path '{real}' is in a read-only access entry (mode={entry.mode!r}). "
                    "Write access is not permitted."
                )
            return real

    raise PermissionError(
        f"Path '{real}' is not within any allowed filesystem access path for this bot."
    )


def _get_fs_access() -> list[FilesystemAccessEntry]:
    bot_id = current_bot_id.get()
    if not bot_id:
        raise PermissionError("No bot context available.")
    return get_bot(bot_id).filesystem_access


@register({
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a file from the host filesystem. Returns file contents as text.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file to read.",
                },
                "offset_line": {
                    "type": "integer",
                    "description": "1-based line number to start reading from (optional).",
                },
                "limit_lines": {
                    "type": "integer",
                    "description": "Maximum number of lines to return (optional).",
                },
            },
            "required": ["path"],
        },
    },
})
async def read_file(path: str, offset_line: int | None = None, limit_lines: int | None = None) -> str:
    try:
        real = _resolve_and_check(path, _get_fs_access(), require_write=False)
    except PermissionError as e:
        return json.dumps({"error": "access_denied", "message": str(e)})

    if not real.is_file():
        return json.dumps({"error": "not_found", "message": f"File not found: {real}"})

    try:
        raw = real.read_bytes()
    except OSError as e:
        return json.dumps({"error": "io_error", "message": str(e)})

    truncated = False
    if len(raw) > settings.FS_COMMANDS_MAX_READ_BYTES:
        raw = raw[:settings.FS_COMMANDS_MAX_READ_BYTES]
        truncated = True

    content = raw.decode(errors="replace")

    if offset_line is not None or limit_lines is not None:
        lines = content.splitlines(keepends=True)
        start = max(0, (offset_line or 1) - 1)
        end = start + limit_lines if limit_lines is not None else None
        content = "".join(lines[start:end])

    return json.dumps({
        "path": str(real),
        "content": content,
        "truncated": truncated,
        "size_bytes": real.stat().st_size,
    })


@register({
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Write content to a file on the host filesystem. Requires write access to the path.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file to write.",
                },
                "content": {
                    "type": "string",
                    "description": "Text content to write to the file.",
                },
                "create_parents": {
                    "type": "boolean",
                    "description": "Create parent directories if they do not exist (default false).",
                },
            },
            "required": ["path", "content"],
        },
    },
})
async def write_file(path: str, content: str, create_parents: bool = False) -> str:
    try:
        real = _resolve_and_check(path, _get_fs_access(), require_write=True)
    except PermissionError as e:
        return json.dumps({"error": "access_denied", "message": str(e)})

    try:
        if create_parents:
            real.parent.mkdir(parents=True, exist_ok=True)
        real.write_text(content, encoding="utf-8")
    except OSError as e:
        return json.dumps({"error": "io_error", "message": str(e)})

    return json.dumps({
        "path": str(real),
        "bytes_written": len(content.encode("utf-8")),
        "ok": True,
    })


@register({
    "type": "function",
    "function": {
        "name": "list_directory",
        "description": "List the contents of a directory on the host filesystem.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the directory to list.",
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to filter entries (e.g. '*.py'). Optional.",
                },
                "show_hidden": {
                    "type": "boolean",
                    "description": "Include hidden files/dirs (starting with '.'). Default false.",
                },
            },
            "required": ["path"],
        },
    },
})
async def list_directory(path: str, pattern: str | None = None, show_hidden: bool = False) -> str:
    try:
        real = _resolve_and_check(path, _get_fs_access(), require_write=False)
    except PermissionError as e:
        return json.dumps({"error": "access_denied", "message": str(e)})

    if not real.is_dir():
        return json.dumps({"error": "not_found", "message": f"Directory not found: {real}"})

    try:
        if pattern:
            entries = list(real.glob(pattern))
        else:
            entries = list(real.iterdir())
    except OSError as e:
        return json.dumps({"error": "io_error", "message": str(e)})

    if not show_hidden:
        entries = [e for e in entries if not e.name.startswith(".")]

    entries.sort(key=lambda e: (e.is_file(), e.name.lower()))

    truncated = False
    if len(entries) > settings.FS_COMMANDS_MAX_LIST_ENTRIES:
        entries = entries[:settings.FS_COMMANDS_MAX_LIST_ENTRIES]
        truncated = True

    result = []
    for entry in entries:
        try:
            stat = entry.stat()
            result.append({
                "name": entry.name,
                "type": "file" if entry.is_file() else "dir",
                "size": stat.st_size if entry.is_file() else None,
                "mtime": int(stat.st_mtime),
            })
        except OSError:
            result.append({"name": entry.name, "type": "unknown"})

    return json.dumps({
        "path": str(real),
        "entries": result,
        "count": len(result),
        "truncated": truncated,
    })


@register({
    "type": "function",
    "function": {
        "name": "find_files",
        "description": "Recursively find files matching a glob pattern under a root directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "root": {
                    "type": "string",
                    "description": "Absolute path to the directory to search from.",
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern to match (e.g. '**/*.py', '*.md').",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 500).",
                },
            },
            "required": ["root", "pattern"],
        },
    },
})
async def find_files(root: str, pattern: str, max_results: int = 500) -> str:
    try:
        real_root = _resolve_and_check(root, _get_fs_access(), require_write=False)
    except PermissionError as e:
        return json.dumps({"error": "access_denied", "message": str(e)})

    if not real_root.is_dir():
        return json.dumps({"error": "not_found", "message": f"Directory not found: {real_root}"})

    cap = min(max_results, 500)
    matches: list[str] = []
    truncated = False

    try:
        for p in real_root.rglob(pattern):
            if len(matches) >= cap:
                truncated = True
                break
            matches.append(str(p))
    except OSError as e:
        return json.dumps({"error": "io_error", "message": str(e)})

    return json.dumps({
        "root": str(real_root),
        "pattern": pattern,
        "matches": matches,
        "count": len(matches),
        "truncated": truncated,
    })
