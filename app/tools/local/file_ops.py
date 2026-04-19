"""file — direct file operations inside the bot's workspace.

Bypasses shell entirely, avoiding quoting/escaping issues with exec_command.
Operations: read, create, overwrite, append, edit, json_patch, history, restore,
list, delete, mkdir, move, grep, glob.
"""
from __future__ import annotations

import copy
import difflib
import fnmatch
import glob as glob_mod
import json
import logging
import os
import re
import time
from pathlib import Path

from app.agent.context import current_bot_id
from app.tools.registry import register

logger = logging.getLogger(__name__)

MAX_CONTENT_BYTES = 1_048_576  # 1 MB
MAX_READ_LINES = 2000
DEFAULT_READ_LINES = 500

# grep / glob limits
MAX_GREP_MATCHES = 500
DEFAULT_GREP_MATCHES = 100
MAX_GLOB_RESULTS = 2000
DEFAULT_GLOB_RESULTS = 500
MAX_GREP_FILES_SCANNED = 20000
MAX_GREP_FILE_BYTES = 5_242_880  # 5 MB — skip files larger than this during grep
GREP_LINE_MAX_CHARS = 400

# Versioned backups retained in a sibling .versions/ directory. Data files
# (.json/.yaml/.yml/.toml) keep a longer rollback window since structured
# data is both more valuable to recover and more often touched by patches.
MAX_BACKUP_VERSIONS_DEFAULT = 5
MAX_BACKUP_VERSIONS_DATA = 20
_DATA_FILE_EXTS = frozenset({".json", ".yaml", ".yml", ".toml"})
MAX_BACKUP_VERSIONS = MAX_BACKUP_VERSIONS_DEFAULT

# Read-before-overwrite tracking: the `overwrite` op requires the bot to have
# called `read` on the same path within this window. Matches Claude Code's
# Write tool precondition.
_RECENT_READS: dict[tuple[str, str], float] = {}
_READ_FRESHNESS_SECONDS = 600  # 10 min — covers a typical run

# Directories pruned from recursive grep / glob — keeps output focused on
# source and avoids blowing context on vendored / build / VCS junk.
_SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn",
    "node_modules", "bower_components",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "env",
    "dist", "build", ".next", ".turbo", ".parcel-cache",
    ".cache", ".tox", "target",
    ".versions",  # write-safety backups — internal, never surface to bots
})

_CHANNEL_PATH_RE = re.compile(r"^/workspace/channels/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:/|$)")


# Mimetype for the rendered envelope, picked off file extension. Used by
# _op_read to give the web UI enough hint to choose markdown / json-tree /
# plain-text rendering. Bots opting into custom envelopes (write/edit diffs,
# grep listings, etc.) compose their own mimetypes inline.
_MARKDOWN_EXTS = frozenset({".md", ".mdx", ".markdown"})
_JSON_EXTS = frozenset({".json"})


def _mimetype_for_path(path: str) -> str:
    """Pick a render mimetype from a file extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext in _MARKDOWN_EXTS:
        return "text/markdown"
    if ext in _JSON_EXTS:
        return "application/json"
    return "text/plain"


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

    # Determine shared workspace root
    shared_root: str | None = None
    if bot and bot.shared_workspace_id:
        from app.services.shared_workspace import shared_workspace_service
        shared_root = os.path.realpath(
            shared_workspace_service.get_host_root(bot.shared_workspace_id)
        )

    # Translate container-style /workspace/... paths
    if path.startswith("/workspace/") or path == "/workspace":
        path = workspace_service.translate_path(
            bot.id, path, bot.workspace, bot=bot,
        )

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
        # Orchestrators can read all bot directories in the shared workspace.
        is_orchestrator = getattr(bot, "shared_workspace_role", None) == "orchestrator"
        if not is_orchestrator:
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
    return json.dumps({"error": msg}, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "file",
        "description": (
            "Direct file operations inside your workspace. Bypasses shell — "
            "no quoting issues with apostrophes, backticks, or special characters. "
            "Operations: read, create (new file, errors if exists), overwrite (full "
            "rewrite after reading), append, edit (find/replace), json_patch (RFC "
            "6902 on JSON), history, restore, list, delete, mkdir, move, grep, glob. "
            "Use grep for literal/regex text search across files (complements "
            "search_workspace, which is semantic). Use glob to find files by filename "
            "pattern (e.g. '**/*.py')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": [
                        "read", "create", "overwrite", "append", "edit",
                        "json_patch", "history", "restore",
                        "list", "delete", "mkdir", "move",
                        "grep", "glob",
                    ],
                    "description": (
                        "The file operation to perform. `create` makes a new file "
                        "and errors if the path exists — use it for every new-file "
                        "write. `overwrite` fully rewrites an existing file and "
                        "requires you to have just called `read` on it (this is the "
                        "safety rail that blocks 'wrote a shrunken version' bugs). "
                        "`json_patch` applies RFC 6902 ops to JSON — use this for "
                        "data files so keys you didn't mention aren't dropped. "
                        "`edit` is find/replace, the safest op for narrative files. "
                        "`history` lists backups for a path; `restore` rolls back to one."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": (
                        "File or directory path. Relative paths resolve from workspace root "
                        "('.' = workspace root). Container paths (/workspace/...) are translated "
                        "automatically. For grep, this is the search root (file or directory). "
                        "For glob, this is the base directory to glob from."
                    ),
                },
                "destination": {
                    "type": "string",
                    "description": "Destination path for move operation. Creates parent directories automatically.",
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
                    "description": (
                        f"For read: max lines (default {DEFAULT_READ_LINES}, max {MAX_READ_LINES}). "
                        f"For grep: max matches (default {DEFAULT_GREP_MATCHES}, max {MAX_GREP_MATCHES}). "
                        f"For glob: max paths (default {DEFAULT_GLOB_RESULTS}, max {MAX_GLOB_RESULTS})."
                    ),
                },
                "pattern": {
                    "type": "string",
                    "description": (
                        "For grep: Python regex to search for (e.g. 'def \\w+_handler'). "
                        "For glob: filename glob pattern, recursive (e.g. '**/*.py', 'tests/**/test_*.py'). "
                        "Common junk dirs (.git, node_modules, __pycache__, .venv, dist, build, etc.) "
                        "are always skipped."
                    ),
                },
                "include": {
                    "type": "string",
                    "description": (
                        "For grep: optional **basename** glob filter (e.g. '*.py', 'test_*.md'). "
                        "Matched against the filename only — do NOT include path segments "
                        "(a leading '**/' or '*/' is stripped automatically). Limits the scan "
                        "to matching filenames."
                    ),
                },
                "patch": {
                    "type": "array",
                    "description": (
                        "For json_patch: RFC 6902 JSON Patch operations. Each entry: "
                        "{op: add|remove|replace|move|copy|test, path: '/a/b', value: ...}. "
                        "Reads the file, applies patches, writes back — the agent never "
                        "holds the whole file, so unchanged keys cannot be silently dropped."
                    ),
                    "items": {"type": "object"},
                },
                "version": {
                    "type": "string",
                    "description": (
                        "For restore: the backup filename to restore from (from "
                        "history output). Example: 'tracked-shows.json.1776429202-1753.bak'."
                    ),
                },
            },
            "required": ["operation", "path"],
        },
    },
}, safety_tier="mutating", requires_bot_context=True)
async def file(
    operation: str,
    path: str,
    content: str | None = None,
    find: str | None = None,
    replace: str | None = None,
    replace_all: bool = False,
    offset: int | None = None,
    limit: int | None = None,
    destination: str | None = None,
    pattern: str | None = None,
    include: str | None = None,
    patch: list[dict] | None = None,
    version: str | None = None,
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

    # --- Bot hooks: before_access ---
    from app.services.bot_hooks import run_before_access, schedule_after_write
    block_err = await run_before_access(bot_id, path)
    if block_err:
        return _error(block_err)

    _WRITE_OPS = {
        "create", "overwrite", "append", "edit",
        "json_patch", "restore", "delete", "mkdir", "move",
    }

    try:
        if operation == "read":
            result = _op_read(resolved, effective_ws_root, offset, limit)
            # _op_read returns plain numbered text (kept that way so direct unit
            # tests stay simple). Wrap with an envelope here so the web UI gets
            # mimetype-keyed rendering and the LLM still sees the numbered text.
            if not result.startswith('{"error"'):
                _note_read(bot_id, resolved)
                rel = os.path.relpath(resolved, os.path.realpath(effective_ws_root))
                # Body is the file content WITHOUT the line-number gutter so
                # renderers (markdown / json / plain) consume the original.
                try:
                    body_text = Path(resolved).read_text()
                except (OSError, UnicodeDecodeError):
                    body_text = result
                result = json.dumps({
                    "_envelope": {
                        "content_type": _mimetype_for_path(resolved),
                        "body": body_text,
                        "plain_body": f"Read {rel}",
                        "display": "inline",
                    },
                    "llm": result,
                }, ensure_ascii=False)
        elif operation == "create":
            result = _op_create(resolved, content)
        elif operation == "overwrite":
            result = _op_overwrite(resolved, content, bot_id)
        elif operation == "append":
            result = _op_append(resolved, content)
        elif operation == "edit":
            result = _op_edit(resolved, find, replace, replace_all, content=content, bot_id=bot_id)
        elif operation == "json_patch":
            result = _op_json_patch(resolved, patch)
        elif operation == "history":
            result = _op_history(resolved, effective_ws_root)
        elif operation == "restore":
            result = _op_restore(resolved, version)
        elif operation == "list":
            result = _op_list(resolved, effective_ws_root)
        elif operation == "delete":
            result = _op_delete(resolved)
        elif operation == "mkdir":
            result = _op_mkdir(resolved)
        elif operation == "move":
            result = await _op_move(resolved, destination, effective_ws_root, effective_bot)
        elif operation == "grep":
            result = _op_grep(resolved, pattern, include, effective_ws_root, limit)
        elif operation == "glob":
            result = _op_glob(resolved, pattern, effective_ws_root, limit)
        else:
            return _error(f"Unknown operation: {operation}")

        # --- Bot hooks: after_write (debounced) ---
        if operation in _WRITE_OPS and not result.startswith('{"error"'):
            schedule_after_write(bot_id, path)
            # Notify pinned panels (lightweight — returns immediately if path not pinned)
            from app.services.pinned_panels import notify_pinned_file_changed
            await notify_pinned_file_changed(path)

        return result
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


def _make_diff(before: str, after: str, rel_path: str) -> str:
    """Build a unified diff for envelope rendering. Empty if there is no change."""
    diff_lines = list(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{rel_path}",
        tofile=f"b/{rel_path}",
        lineterm="",
    ))
    return "".join(diff_lines)


def _diff_stats(diff_text: str) -> tuple[int, int]:
    """Count added/removed lines in a unified diff body."""
    added = 0
    removed = 0
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def _note_read(bot_id: str | None, path: str) -> None:
    """Record that *bot_id* read *path* just now (for read-before-overwrite)."""
    if not bot_id:
        return
    _RECENT_READS[(bot_id, os.path.realpath(path))] = time.time()


def _is_recently_read(bot_id: str | None, path: str) -> bool:
    """True if *bot_id* read *path* within _READ_FRESHNESS_SECONDS."""
    if not bot_id:
        return False
    ts = _RECENT_READS.get((bot_id, os.path.realpath(path)))
    if ts is None:
        return False
    if time.time() - ts > _READ_FRESHNESS_SECONDS:
        return False
    return True


def _retention_for(path: str) -> int:
    ext = os.path.splitext(path)[1].lower()
    return MAX_BACKUP_VERSIONS_DATA if ext in _DATA_FILE_EXTS else MAX_BACKUP_VERSIONS_DEFAULT


def _save_backup(path: str) -> str | None:
    """Save a timestamped backup of *path* in a .versions/ sibling directory.

    Returns the absolute backup path on success (for inclusion in tool results),
    or None if the source is missing or the copy failed. Retention depends on
    file extension — data files (.json/.yaml/.yml/.toml) keep MAX_BACKUP_VERSIONS_DATA
    copies, everything else keeps MAX_BACKUP_VERSIONS_DEFAULT.
    """
    if not os.path.isfile(path):
        return None

    parent = os.path.dirname(path)
    basename = os.path.basename(path)
    versions_dir = os.path.join(parent, ".versions")
    os.makedirs(versions_dir, exist_ok=True)

    # Use monotonic-ish timestamp with subsecond precision to avoid collisions
    ts = f"{time.time():.4f}".replace(".", "-")
    backup_name = f"{basename}.{ts}.bak"
    backup_path = os.path.join(versions_dir, backup_name)

    try:
        import shutil
        shutil.copy2(path, backup_path)
    except OSError:
        logger.warning("Failed to create backup of %s", path)
        return None

    # Prune old backups for this basename (keep newest per-file retention).
    pattern = os.path.join(versions_dir, f"{basename}.*.bak")
    backups = sorted(glob_mod.glob(pattern), key=lambda p: (os.path.getmtime(p), p), reverse=True)
    retention = _retention_for(path)
    for old in backups[retention:]:
        try:
            os.remove(old)
        except OSError:
            pass

    return backup_path


def _relativize_backup(backup_path: str | None, live_path: str) -> str | None:
    """Return the backup path relative to the live file's parent (compact log line)."""
    if not backup_path:
        return None
    try:
        return os.path.relpath(backup_path, os.path.dirname(live_path))
    except ValueError:
        return backup_path


def _op_create(path: str, content: str | None) -> str:
    """Write a new file; error if *path* already exists.

    Matches POSIX O_CREAT|O_EXCL and str_replace_editor's `create` command.
    Use this for every new-file write so a half-remembered path never clobbers
    an existing doc.
    """
    if content is None:
        return _error("content is required for create.")
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        return _error(f"Content exceeds {MAX_CONTENT_BYTES} byte limit.")
    if os.path.isdir(path):
        return _error(f"Path is a directory: {os.path.basename(path)}")
    if os.path.isfile(path):
        return _error(
            f"File already exists: {os.path.basename(path)}. "
            f"Use operation=\"edit\" for targeted changes, \"append\" to add content, "
            f"or \"overwrite\" (after reading the file) for an intentional full rewrite."
        )

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    Path(path).write_text(content)
    size = os.path.getsize(path)
    rel = os.path.basename(path)
    line_count = content.count("\n") + (0 if content.endswith("\n") or not content else 1)
    return json.dumps({
        "ok": True,
        "bytes": size,
        "created": True,
        "_envelope": {
            "content_type": "text/markdown",
            "body": f"**Created** `{rel}` ({size} bytes, {line_count} lines)",
            "plain_body": f"Created {rel} ({size} bytes, {line_count} lines).",
            "display": "inline",
        },
    }, ensure_ascii=False)


def _op_overwrite(path: str, content: str | None, bot_id: str | None) -> str:
    """Fully rewrite an existing file — requires a prior `read` in the same work.

    Matches Claude Code's Write tool safety pattern: you must have read the
    current contents into context before the model can justify replacing them.
    This forecloses the "wrote a shrunken version because I forgot what else
    was in there" failure mode that prompted this plan.
    """
    if content is None:
        return _error("content is required for overwrite.")
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        return _error(f"Content exceeds {MAX_CONTENT_BYTES} byte limit.")
    if not os.path.isfile(path):
        return _error(
            f"File does not exist: {os.path.basename(path)}. "
            f"Use operation=\"create\" to make a new file."
        )
    if not _is_recently_read(bot_id, path):
        return _error(
            f"Must read the file before overwriting it. Call "
            f"file(operation=\"read\", path=\"{os.path.basename(path)}\") first, "
            f"then retry overwrite. (For JSON data files, prefer json_patch so "
            f"you don't have to hold the whole file in context.)"
        )

    try:
        pre_content = Path(path).read_text()
    except (OSError, UnicodeDecodeError):
        pre_content = ""

    backup_path = _save_backup(path)
    backup_rel = _relativize_backup(backup_path, path)
    Path(path).write_text(content)
    size = os.path.getsize(path)
    rel = os.path.basename(path)
    diff_text = _make_diff(pre_content, content, rel)
    added, removed = _diff_stats(diff_text)
    summary = f"Overwrote {rel}: +{added} −{removed} lines"
    if backup_rel:
        summary += f" (backup: {backup_rel})"
    return json.dumps({
        "ok": True,
        "bytes": size,
        "backup": backup_rel,
        "_envelope": {
            "content_type": "application/vnd.spindrel.diff+text",
            "body": diff_text,
            "plain_body": summary,
            "display": "inline",
        },
    }, ensure_ascii=False)


def _op_json_patch(path: str, patch: list[dict] | None) -> str:
    """Apply an RFC 6902 JSON Patch to *path* and write back.

    The canonical fix for the arr-heartbeat incident class: the agent describes
    which keys to touch, the tool reads-modifies-writes. Unmentioned keys
    survive by construction.
    """
    if not patch:
        return _error(
            "patch is required for json_patch and must be a non-empty list of "
            "RFC 6902 ops (e.g. [{\"op\": \"replace\", \"path\": \"/a/b\", \"value\": 1}])."
        )
    if not isinstance(patch, list) or not all(isinstance(p, dict) for p in patch):
        return _error("patch must be a list of RFC 6902 operation objects.")
    if not os.path.isfile(path):
        return _error(
            f"File does not exist: {os.path.basename(path)}. "
            f"Use operation=\"create\" to make a new JSON file first."
        )

    try:
        raw = Path(path).read_text()
    except (OSError, UnicodeDecodeError) as e:
        return _error(f"Could not read file: {e}")

    try:
        document = json.loads(raw)
    except json.JSONDecodeError as e:
        return _error(
            f"File is not valid JSON ({e.msg} at line {e.lineno}). "
            f"Fix the file first (use read to inspect, then edit/overwrite) "
            f"before applying a patch."
        )

    try:
        import jsonpatch  # type: ignore
    except ImportError:
        return _error(
            "json_patch requires the `jsonpatch` package. Install it via "
            "requirements.txt and restart the agent-server."
        )

    try:
        # Deep-copy so the caller cannot observe partial mutation on error.
        patched = jsonpatch.apply_patch(copy.deepcopy(document), patch)
    except jsonpatch.JsonPatchException as e:
        return _error(f"Patch failed: {e}")
    except jsonpatch.JsonPointerException as e:
        return _error(f"Patch path not found: {e}")

    # Preserve detected formatting: indent + trailing-newline presence.
    indent = _detect_json_indent(raw)
    trailing_newline = raw.endswith("\n")
    new_text = json.dumps(patched, indent=indent, ensure_ascii=False)
    if trailing_newline:
        new_text += "\n"

    backup_path = _save_backup(path)
    backup_rel = _relativize_backup(backup_path, path)
    Path(path).write_text(new_text)
    size = os.path.getsize(path)
    rel = os.path.basename(path)
    diff_text = _make_diff(raw, new_text, rel)
    added, removed = _diff_stats(diff_text)
    applied = len(patch)
    summary = f"Applied {applied} patch op(s) to {rel}: +{added} −{removed} lines"
    if backup_rel:
        summary += f" (backup: {backup_rel})"
    return json.dumps({
        "ok": True,
        "bytes": size,
        "applied": applied,
        "backup": backup_rel,
        "_envelope": {
            "content_type": "application/vnd.spindrel.diff+text",
            "body": diff_text,
            "plain_body": summary,
            "display": "inline",
        },
    }, ensure_ascii=False)


def _detect_json_indent(raw: str) -> int:
    """Infer indent width from *raw* JSON text. Falls back to 2."""
    m = re.match(r"^[\[{]\n( +)", raw)
    if m:
        return len(m.group(1))
    return 2


def _op_history(path: str, ws_root: str) -> str:
    """List `.versions/` backups for *path*."""
    parent = os.path.dirname(path)
    basename = os.path.basename(path)
    versions_dir = os.path.join(parent, ".versions")
    if not os.path.isdir(versions_dir):
        rel = os.path.relpath(path, os.path.realpath(ws_root))
        return json.dumps({
            "ok": True,
            "path": rel,
            "versions": [],
            "_envelope": {
                "content_type": "text/markdown",
                "body": f"No backups yet for `{rel}`.",
                "plain_body": f"No backups yet for {rel}.",
                "display": "inline",
            },
        }, ensure_ascii=False)

    pattern = os.path.join(versions_dir, f"{basename}.*.bak")
    backups = sorted(glob_mod.glob(pattern), key=os.path.getmtime, reverse=True)
    versions = []
    for bp in backups:
        try:
            st = os.stat(bp)
        except OSError:
            continue
        versions.append({
            "version": os.path.basename(bp),
            "bytes": st.st_size,
            "modified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
        })

    rel = os.path.relpath(path, os.path.realpath(ws_root))
    lines = [f"**Backups for `{rel}`** ({len(versions)} version(s)):", ""]
    lines.extend(
        f"- `{v['version']}` — {v['bytes']} bytes, {v['modified_at']}" for v in versions
    )
    return json.dumps({
        "ok": True,
        "path": rel,
        "versions": versions,
        "_envelope": {
            "content_type": "text/markdown",
            "body": "\n".join(lines),
            "plain_body": f"Listed {len(versions)} backup(s) for {rel}.",
            "display": "inline",
        },
    }, ensure_ascii=False)


def _op_restore(path: str, version: str | None) -> str:
    """Restore *path* from a `.versions/` backup; current state is itself backed up first."""
    if not version:
        return _error(
            "version is required for restore (filename from `history` output, "
            "e.g. 'tracked-shows.json.1776429202-1753.bak')."
        )
    if "/" in version or ".." in version:
        return _error("version must be a plain filename, not a path.")

    parent = os.path.dirname(path)
    versions_dir = os.path.join(parent, ".versions")
    backup_path = os.path.join(versions_dir, version)
    if not os.path.isfile(backup_path):
        return _error(f"Backup not found: {version}. Call operation=\"history\" to list.")

    basename = os.path.basename(path)
    if not version.startswith(basename + "."):
        return _error(f"Backup {version} does not belong to {basename}.")

    # Back up current live state before overwriting it — restore is itself undoable.
    prior_backup_rel = None
    if os.path.isfile(path):
        prior_backup = _save_backup(path)
        prior_backup_rel = _relativize_backup(prior_backup, path)

    try:
        import shutil
        shutil.copy2(backup_path, path)
    except OSError as e:
        return _error(f"Restore failed: {e}")

    size = os.path.getsize(path)
    rel = os.path.basename(path)
    summary = f"Restored {rel} from {version} ({size} bytes)."
    if prior_backup_rel:
        summary += f" Prior state saved as {prior_backup_rel}."
    return json.dumps({
        "ok": True,
        "bytes": size,
        "restored_from": version,
        "prior_backup": prior_backup_rel,
        "_envelope": {
            "content_type": "text/markdown",
            "body": summary,
            "plain_body": summary,
            "display": "inline",
        },
    }, ensure_ascii=False)


def _op_append(path: str, content: str | None) -> str:
    if content is None:
        return _error("content is required for append.")
    if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
        return _error(f"Content exceeds {MAX_CONTENT_BYTES} byte limit.")

    pre_content = ""
    if os.path.isfile(path):
        try:
            pre_content = Path(path).read_text()
        except (OSError, UnicodeDecodeError):
            pre_content = ""

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
    rel = os.path.basename(path)
    post_content = pre_content + prefix + content
    diff_text = _make_diff(pre_content, post_content, rel)
    added, _removed = _diff_stats(diff_text)
    return json.dumps({
        "ok": True,
        "bytes": size,
        "_envelope": {
            "content_type": "application/vnd.spindrel.diff+text",
            "body": diff_text,
            "plain_body": f"Appended {added} lines to {rel}",
            "display": "inline",
        },
    }, ensure_ascii=False)


def _whitespace_flex_pattern(find: str) -> re.Pattern | None:
    """Build a regex matching *find* with flexible whitespace.

    Non-whitespace tokens must appear in order and match exactly;
    any whitespace between them is allowed to differ in amount or type
    (spaces, tabs, newlines).  Returns None if *find* has no tokens.
    """
    parts = find.split()
    if not parts:
        return None
    pattern = r"\s+".join(re.escape(p) for p in parts)
    return re.compile(pattern, re.DOTALL)


def _find_closest_hint(find: str, text: str) -> str:
    """Return a hint showing the most similar block in *text*."""
    find_lines = [l.strip() for l in find.strip().splitlines() if l.strip()]
    text_lines = text.splitlines()
    if not find_lines or not text_lines:
        return ""

    target = find_lines[0]
    best_ratio = 0.0
    best_idx = 0
    for i, line in enumerate(text_lines):
        ratio = difflib.SequenceMatcher(None, target, line.strip()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_idx = i

    if best_ratio < 0.4:
        return ""

    window = max(len(find_lines) + 2, 5)
    start = max(0, best_idx - 1)
    end = min(len(text_lines), start + window)
    snippet = "\n".join(text_lines[start:end])
    if len(snippet) > 500:
        snippet = snippet[:500] + "..."

    return (
        " The closest matching text in the file is:\n"
        f'"""\n{snippet}\n"""'
    )


def _op_edit(path: str, find: str | None, replace: str | None, replace_all: bool,
             content: str | None = None, bot_id: str | None = None) -> str:
    # Auto-recover when LLM passes content instead of find/replace
    if find is None and content is not None:
        if replace is not None and replace != content:
            # LLM put old text in content, new text in replace → treat content as find
            find = content
        else:
            # LLM just wants to overwrite — route to the safe overwrite op so the
            # read-before-write precondition still applies.
            logger.info("edit: no find provided, routing to overwrite for %s", path)
            if not os.path.isfile(path):
                return _op_create(path, content)
            return _op_overwrite(path, content, bot_id)
    if find is None:
        return _error(
            "find is required for edit. For a full rewrite, read the file first "
            "then call operation=\"overwrite\". For structured JSON changes, use "
            "operation=\"json_patch\"."
        )
    if replace is None:
        replace = content if content is not None else None
    if replace is None:
        return _error("replace is required for edit.")
    if not os.path.isfile(path):
        return _error("File not found.")

    text = Path(path).read_text()

    rel = os.path.basename(path)

    def _edit_envelope(new_text: str, count: int, *, matched: str | None = None) -> dict:
        diff_text = _make_diff(text, new_text, rel)
        added, removed = _diff_stats(diff_text)
        out: dict = {
            "ok": True,
            "replacements": count,
            "_envelope": {
                "content_type": "application/vnd.spindrel.diff+text",
                "body": diff_text,
                "plain_body": f"Edited {rel}: +{added} −{removed} lines ({count} replacement{'s' if count != 1 else ''})",
                "display": "inline",
            },
        }
        if matched:
            out["matched"] = matched
        return out

    # 1. Exact match — fastest, safest
    if find in text:
        if replace_all:
            count = text.count(find)
            new_text = text.replace(find, replace)
        else:
            count = 1
            new_text = text.replace(find, replace, 1)
        Path(path).write_text(new_text)
        return json.dumps(_edit_envelope(new_text, count), ensure_ascii=False)

    # 2. Whitespace-normalized match — handles LLM whitespace drift
    pat = _whitespace_flex_pattern(find)
    if pat:
        # Cap accepted span at 2x the find length to prevent runaway matches
        # bridging distant tokens across many blank lines.
        max_span = max(len(find) * 2, 200)
        matches = [m for m in pat.finditer(text) if m.end() - m.start() <= max_span]
        if matches:
            if replace_all:
                count = len(matches)
                new_text = text
                for m in reversed(matches):
                    new_text = new_text[:m.start()] + replace + new_text[m.end():]
            else:
                count = 1
                m = matches[0]
                new_text = text[:m.start()] + replace + text[m.end():]
            Path(path).write_text(new_text)
            logger.info("edit: whitespace-flex match on %s (%d replacement(s))", path, count)
            return json.dumps(_edit_envelope(new_text, count, matched="whitespace-normalized"), ensure_ascii=False)

    # 3. Line-contains match — find is a long substring of exactly one line
    # Handles the common case where the LLM omits a bullet prefix or trailing text.
    if len(find.strip()) >= 60:
        _find_stripped = find.strip()
        _matching_lines = [
            (i, line) for i, line in enumerate(text.splitlines())
            if _find_stripped in line or line.strip() in _find_stripped
        ]
        if len(_matching_lines) == 1:
            _idx, _matched_line = _matching_lines[0]
            # Replace the entire line, preserving the line's leading whitespace
            lines = text.splitlines(keepends=True)
            _leading = lines[_idx][:len(lines[_idx]) - len(lines[_idx].lstrip())]
            lines[_idx] = _leading + replace.lstrip() + "\n"
            new_text = "".join(lines)
            Path(path).write_text(new_text)
            logger.info("edit: line-contains match on %s (line %d)", path, _idx + 1)
            return json.dumps(_edit_envelope(new_text, 1, matched="line-contains"), ensure_ascii=False)

    # 4. No match — provide helpful error with closest text
    hint = _find_closest_hint(find, text)
    return _error(f"find string not found in file.{hint}")


def _op_list(path: str, ws_root: str) -> str:
    if not os.path.isdir(path):
        return _error("Not a directory.")

    entries = []
    try:
        items = sorted(os.listdir(path))
    except PermissionError:
        return _error("Permission denied.")

    dirs_first = sorted(items, key=lambda x: (not os.path.isdir(os.path.join(path, x)), x))

    # Directories hidden from direct listings — only internal/implementation dirs.
    # _SKIP_DIRS is for recursive grep/glob; this is a smaller set for ls-style listing.
    _LIST_HIDDEN = frozenset({".versions"})
    for name in dirs_first:
        if name in _LIST_HIDDEN:
            continue
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
    listing = {"path": rel, "entries": entries}
    n_dirs = sum(1 for e in entries if e["type"] == "dir")
    n_files = sum(1 for e in entries if e["type"] == "file")
    return json.dumps({
        **listing,
        "_envelope": {
            "content_type": "application/vnd.spindrel.file-listing+json",
            "body": json.dumps(listing, ensure_ascii=False),
            "plain_body": f"Listed {rel}: {n_dirs} dir(s), {n_files} file(s)",
            "display": "inline",
        },
    }, ensure_ascii=False)


def _op_delete(path: str) -> str:
    if os.path.isdir(path):
        return _error("Cannot delete directories — only individual files.")
    if not os.path.exists(path):
        return _error("File not found.")

    rel = os.path.basename(path)
    os.remove(path)
    return json.dumps({
        "ok": True,
        "deleted": True,
        "_envelope": {
            "content_type": "text/markdown",
            "body": f"**Deleted** `{rel}`",
            "plain_body": f"Deleted {rel}",
            "display": "inline",
        },
    }, ensure_ascii=False)


def _op_mkdir(path: str) -> str:
    rel = os.path.basename(path) or path
    os.makedirs(path, exist_ok=True)
    return json.dumps({
        "ok": True,
        "created": True,
        "_envelope": {
            "content_type": "text/markdown",
            "body": f"**Created directory** `{rel}`",
            "plain_body": f"Created directory {rel}",
            "display": "inline",
        },
    }, ensure_ascii=False)


async def _op_move(src: str, destination: str | None, ws_root: str, bot) -> str:
    """Move/rename a file or directory within the workspace."""
    if destination is None:
        return _error("destination is required for move.")
    if not os.path.exists(src):
        return _error("Source not found.")

    try:
        dest = _resolve_path(destination, ws_root, bot)
    except ValueError as e:
        return _error(f"Invalid destination: {e}")

    # If dest is an existing directory, move source into it (like `mv`)
    if os.path.isdir(dest):
        dest = os.path.join(dest, os.path.basename(src))

    if os.path.exists(dest):
        return _error(f"Destination already exists: {destination}")

    os.makedirs(os.path.dirname(dest), exist_ok=True)
    import shutil
    src_rel = os.path.basename(src)
    shutil.move(src, dest)
    return json.dumps({
        "ok": True,
        "moved": destination,
        "_envelope": {
            "content_type": "text/markdown",
            "body": f"**Moved** `{src_rel}` → `{destination}`",
            "plain_body": f"Moved {src_rel} → {destination}",
            "display": "inline",
        },
    }, ensure_ascii=False)


def _looks_binary(path: str) -> bool:
    """Heuristic: a NUL byte in the first 8KB marks the file as binary."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
    except OSError:
        return True
    return b"\x00" in chunk


def _normalize_include(include: str | None) -> str | None:
    """Strip a leading ``**/`` or ``*/`` from the include filter.

    ``include`` is matched against the file's basename with ``fnmatch``, which
    doesn't understand path globs. Bots habitually write ``**/*.py`` when they
    mean "any .py anywhere" — without this normalization that silently matches
    zero files.
    """
    if not include:
        return include
    normalized = include
    for prefix in ("**/", "*/"):
        while normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
    return normalized or include


def _is_within(path: str, root_real: str) -> bool:
    """True if ``path``'s realpath is contained by ``root_real``."""
    try:
        real = os.path.realpath(path)
    except OSError:
        return False
    return real == root_real or real.startswith(root_real + os.sep)


def _iter_grep_targets(root: str, include: str | None, boundary: str):
    """Walk *root*, yielding file paths while pruning _SKIP_DIRS.

    If *root* is a single file, yields just that file. Respects the optional
    filename-glob *include* filter (matched against basename). Skips entries
    whose realpath escapes *boundary* (symlinks pointing outside the
    workspace).
    """
    include = _normalize_include(include)

    if os.path.isfile(root):
        if include is None or fnmatch.fnmatch(os.path.basename(root), include):
            if _is_within(root, boundary):
                yield root
        return

    count = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Prune junk dirs in-place so os.walk skips them entirely.
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            if include is not None and not fnmatch.fnmatch(fname, include):
                continue
            fpath = os.path.join(dirpath, fname)
            # Defense-in-depth: skip symlinks that escape the workspace.
            if not _is_within(fpath, boundary):
                continue
            yield fpath
            count += 1
            if count >= MAX_GREP_FILES_SCANNED:
                return


def _op_grep(
    root: str,
    pattern: str | None,
    include: str | None,
    ws_root: str,
    limit: int | None,
) -> str:
    """Recursive literal/regex text search over workspace files.

    Complements ``search_workspace`` (semantic). Use grep when you know the
    exact string or a regex — function names, error messages, config keys,
    import paths. Returns structured JSON with file/line/text per match.
    """
    if not pattern:
        return _error("pattern is required for grep.")
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return _error(f"Invalid regex: {e}")
    ws_real = os.path.realpath(ws_root)
    if not os.path.exists(root):
        return _error(f"Path not found: {os.path.relpath(root, ws_real)}")

    # `limit is not None` — don't coerce limit=0 to DEFAULT.
    requested = DEFAULT_GREP_MATCHES if limit is None else max(0, limit)
    max_matches = min(requested, MAX_GREP_MATCHES)
    if max_matches == 0:
        return json.dumps({
            "matches": [], "count": 0, "files_scanned": 0, "truncated": False,
        }, ensure_ascii=False)

    matches: list[dict] = []
    files_scanned = 0
    files_skipped_large = 0
    truncated = False

    for fpath in _iter_grep_targets(root, include, ws_real):
        files_scanned += 1
        try:
            if os.path.getsize(fpath) > MAX_GREP_FILE_BYTES:
                files_skipped_large += 1
                continue
        except OSError:
            continue
        if _looks_binary(fpath):
            continue
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                for lineno, line in enumerate(f, start=1):
                    if regex.search(line):
                        text = line.rstrip("\n")
                        if len(text) > GREP_LINE_MAX_CHARS:
                            text = text[:GREP_LINE_MAX_CHARS] + "…"
                        matches.append({
                            "file": os.path.relpath(fpath, ws_real),
                            "line": lineno,
                            "text": text,
                        })
                        if len(matches) >= max_matches:
                            truncated = True
                            break
        except OSError:
            continue
        if truncated:
            break

    result = {
        "matches": matches,
        "count": len(matches),
        "files_scanned": files_scanned,
        "truncated": truncated,
    }
    if files_skipped_large:
        result["files_skipped_large"] = files_skipped_large
    files_with_hits = len({m["file"] for m in matches}) if matches else 0
    return json.dumps({
        **result,
        "_envelope": {
            "content_type": "application/vnd.spindrel.file-listing+json",
            "body": json.dumps({"kind": "grep", **result}, ensure_ascii=False),
            "plain_body": (
                f"{len(matches)} match(es) in {files_with_hits} file(s)"
                f" — scanned {files_scanned}"
                + (" (truncated)" if truncated else "")
            ),
            "display": "inline",
        },
    }, ensure_ascii=False)


def _op_glob(root: str, pattern: str | None, ws_root: str, limit: int | None) -> str:
    """Find files by filename pattern, recursive from *root*.

    Use when you know what files you want by name (``**/*.py``,
    ``tests/**/test_auth*.py``) rather than what's inside them. Results are
    sorted by modification time descending **before** truncation, so
    ``limit=N`` returns the N most-recently-modified matches — not the first
    N in walk order. Junk dirs (``.git``, ``node_modules``, build artifacts,
    …) and symlinks escaping the workspace are always skipped.
    """
    if not pattern:
        return _error("pattern is required for glob.")
    if not os.path.isdir(root):
        return _error("glob requires a directory path.")

    # `limit is not None` — don't coerce limit=0 to DEFAULT.
    requested = DEFAULT_GLOB_RESULTS if limit is None else max(0, limit)
    max_results = min(requested, MAX_GLOB_RESULTS)

    ws_real = os.path.realpath(ws_root)
    base = Path(root)

    # Collect up to the absolute cap; we sort before applying the user's
    # limit so "newest first" is honored even under truncation.
    results: list[tuple[float, str]] = []
    hit_cap = False
    try:
        for p in base.glob(pattern):
            try:
                rel_parts = p.relative_to(base).parts
            except ValueError:
                continue
            if any(part in _SKIP_DIRS for part in rel_parts):
                continue
            # Defense-in-depth: skip entries whose realpath escapes the workspace.
            if not _is_within(str(p), ws_real):
                continue
            try:
                mtime = p.stat().st_mtime
            except OSError:
                mtime = 0.0
            results.append((mtime, os.path.relpath(str(p), ws_real)))
            if len(results) >= MAX_GLOB_RESULTS:
                hit_cap = True
                break
    except (OSError, ValueError, NotImplementedError) as e:
        return _error(f"glob failed: {e}")

    results.sort(key=lambda t: t[0], reverse=True)
    truncated = hit_cap or len(results) > max_results
    paths = [rel for _mtime, rel in results[:max_results]]

    listing = {"paths": paths, "count": len(paths), "truncated": truncated}
    return json.dumps({
        **listing,
        "_envelope": {
            "content_type": "application/vnd.spindrel.file-listing+json",
            "body": json.dumps({"kind": "glob", **listing}, ensure_ascii=False),
            "plain_body": (
                f"Found {len(paths)} file(s)" + (" (truncated)" if truncated else "")
            ),
            "display": "inline",
        },
    }, ensure_ascii=False)
