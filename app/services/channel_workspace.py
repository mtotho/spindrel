"""Channel workspace service — resolves paths and performs file ops for channel workspaces.

Channel workspaces live inside the shared workspace (or bot workspace) at:
  {ws_root}/channels/{channel_id}/
  {ws_root}/channels/{channel_id}/archive/
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.bots import BotConfig

logger = logging.getLogger(__name__)


def _migrate_old_layout(channel_dir: str, channel_id: str) -> None:
    """Fix old broken directory layouts, idempotent.

    Known bad layouts:
      1. channels/{id}/{id}/ — double-nested GUID (old bug)
      2. channels/{id}/workspace/ — unnecessary nesting (old layout)
    """
    try:
        # Case 1: double-nested GUID — channels/{id}/{id}/{archive,data,...}
        double_nested = os.path.join(channel_dir, channel_id)
        if os.path.isdir(double_nested):
            logger.info("Migrating double-nested channel dir: %s → %s", double_nested, channel_dir)
            for entry in os.scandir(double_nested):
                dest = os.path.join(channel_dir, entry.name)
                if entry.name == ".channel_info":
                    continue  # will be rewritten
                if os.path.exists(dest):
                    if entry.is_dir() and os.path.isdir(dest):
                        for sub in os.scandir(entry.path):
                            sub_dest = os.path.join(dest, sub.name)
                            if not os.path.exists(sub_dest):
                                shutil.move(sub.path, sub_dest)
                else:
                    shutil.move(entry.path, dest)
            try:
                shutil.rmtree(double_nested)
            except Exception:
                pass

        # Case 2: old workspace/ subdirectory — flatten into channel_dir
        old_ws = os.path.join(channel_dir, "workspace")
        if os.path.isdir(old_ws):
            logger.info("Flattening old workspace/ subdir: %s → %s", old_ws, channel_dir)
            for entry in os.scandir(old_ws):
                dest = os.path.join(channel_dir, entry.name)
                if entry.name == ".channel_info":
                    continue  # will be rewritten
                if os.path.exists(dest):
                    if entry.is_dir() and os.path.isdir(dest):
                        for sub in os.scandir(entry.path):
                            sub_dest = os.path.join(dest, sub.name)
                            if not os.path.exists(sub_dest):
                                shutil.move(sub.path, sub_dest)
                else:
                    shutil.move(entry.path, dest)
            try:
                shutil.rmtree(old_ws)
            except Exception:
                pass
    except Exception:
        logger.warning("Failed to migrate old channel workspace layout for %s", channel_id, exc_info=True)


def _get_ws_root(bot: "BotConfig") -> str:
    """Get the workspace root for channel workspaces."""
    if bot.shared_workspace_id:
        from app.services.shared_workspace import shared_workspace_service
        return shared_workspace_service.get_host_root(bot.shared_workspace_id)
    from app.services.workspace import workspace_service
    return workspace_service.get_workspace_root(bot.id, bot)


def get_channel_workspace_root(channel_id: str, bot: "BotConfig") -> str:
    """Returns {ws_root}/channels/{channel_id}/"""
    ws_root = _get_ws_root(bot)
    return os.path.join(ws_root, "channels", channel_id)


def get_channel_archive_root(channel_id: str, bot: "BotConfig") -> str:
    """Returns {ws_root}/channels/{channel_id}/archive/"""
    return os.path.join(get_channel_workspace_root(channel_id, bot), "archive")


def ensure_channel_workspace(
    channel_id: str,
    bot: "BotConfig",
    *,
    display_name: str | None = None,
) -> str:
    """Create archive/ + data/ dirs inside channel dir, idempotent. Returns channel workspace root."""
    ws_path = get_channel_workspace_root(channel_id, bot)

    # Migrate old broken directory structures
    _migrate_old_layout(ws_path, channel_id)

    for subdir in ("archive", "data"):
        os.makedirs(os.path.join(ws_path, subdir), exist_ok=True)

    # Write/update .channel_info so humans can identify UUID folders.
    # If no display_name provided, preserve existing display_name from .channel_info
    # rather than overwriting with the bare channel_id UUID.
    label = display_name
    if not label:
        info_path = os.path.join(ws_path, ".channel_info")
        try:
            if os.path.isfile(info_path):
                for line in Path(info_path).read_text().splitlines():
                    if line.startswith("display_name:"):
                        existing_name = line.split(":", 1)[1].strip()
                        if existing_name and existing_name != channel_id:
                            label = existing_name
                            break
        except Exception:
            pass
    label = label or channel_id

    info_content = f"channel_id: {channel_id}\ndisplay_name: {label}\n"
    info_path = os.path.join(ws_path, ".channel_info")
    try:
        existing = Path(info_path).read_text() if os.path.isfile(info_path) else ""
        if existing != info_content:
            Path(info_path).write_text(info_content)
    except Exception:
        pass  # non-critical

    return ws_path


def list_workspace_files(
    channel_id: str,
    bot: "BotConfig",
    include_archive: bool = False,
    include_data: bool = False,
) -> list[dict]:
    """List .md files in workspace root + optionally archive/ and data/ files."""
    ws_path = get_channel_workspace_root(channel_id, bot)
    files: list[dict] = []

    if os.path.isdir(ws_path):
        for entry in sorted(os.scandir(ws_path), key=lambda e: e.name):
            if entry.is_file() and entry.name.endswith(".md"):
                stat = entry.stat()
                files.append({
                    "name": entry.name,
                    "path": entry.name,
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                    "section": "active",
                })

    if include_archive:
        archive_path = os.path.join(ws_path, "archive")
        if os.path.isdir(archive_path):
            for entry in sorted(os.scandir(archive_path), key=lambda e: e.name):
                if entry.is_file() and entry.name.endswith(".md"):
                    stat = entry.stat()
                    files.append({
                        "name": entry.name,
                        "path": f"archive/{entry.name}",
                        "size": stat.st_size,
                        "modified_at": stat.st_mtime,
                        "section": "archive",
                    })

    if include_data:
        data_path = os.path.join(ws_path, "data")
        if os.path.isdir(data_path):
            for dirpath, _dirnames, filenames in os.walk(data_path):
                _dirnames.sort()
                for fname in sorted(filenames):
                    fpath = os.path.join(dirpath, fname)
                    rel = os.path.relpath(fpath, ws_path)  # e.g. "data/spindrel/file.md"
                    stat = os.stat(fpath)
                    files.append({
                        "name": os.path.relpath(fpath, data_path),  # e.g. "spindrel/file.md"
                        "path": rel,
                        "size": stat.st_size,
                        "modified_at": stat.st_mtime,
                        "section": "data",
                    })

    return files


def read_workspace_file(channel_id: str, bot: "BotConfig", path: str) -> str | None:
    """Read a file from the channel workspace. Returns None if not found or path escapes."""
    ws_path = get_channel_workspace_root(channel_id, bot)
    ws_real = os.path.realpath(ws_path)
    target = os.path.realpath(os.path.join(ws_path, path))
    # Security: ensure path stays within workspace (trailing sep prevents /ws_evil matching /ws)
    if not (target == ws_real or target.startswith(ws_real + os.sep)):
        return None
    if not os.path.isfile(target):
        return None
    try:
        return Path(target).read_text()
    except Exception:
        logger.exception("Failed to read channel workspace file: %s", target)
        return None


def write_workspace_file(channel_id: str, bot: "BotConfig", path: str, content: str) -> dict:
    """Write a file to the channel workspace. Creates parent dirs if needed."""
    ws_path = get_channel_workspace_root(channel_id, bot)
    ws_real = os.path.realpath(ws_path)
    target = os.path.realpath(os.path.join(ws_real, path))
    if not (target == ws_real or target.startswith(ws_real + os.sep)):
        raise ValueError("Path escapes workspace root")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)
    return {"path": path, "size": os.path.getsize(target)}


def delete_workspace_file(channel_id: str, bot: "BotConfig", path: str) -> dict:
    """Delete a file from the channel workspace."""
    ws_path = get_channel_workspace_root(channel_id, bot)
    ws_real = os.path.realpath(ws_path)
    target = os.path.realpath(os.path.join(ws_path, path))
    if not (target == ws_real or target.startswith(ws_real + os.sep)):
        raise ValueError("Path escapes workspace root")
    if not os.path.isfile(target):
        raise FileNotFoundError(f"File not found: {path}")
    os.remove(target)
    return {"path": path, "deleted": True}


def move_workspace_file(channel_id: str, bot: "BotConfig", old_path: str, new_path: str) -> dict:
    """Move/rename a file within the channel workspace."""
    ws_path = get_channel_workspace_root(channel_id, bot)
    ws_real = os.path.realpath(ws_path)

    src = os.path.realpath(os.path.join(ws_real, old_path))
    dst = os.path.realpath(os.path.join(ws_real, new_path))

    if not (src == ws_real or src.startswith(ws_real + os.sep)):
        raise ValueError("Source path escapes workspace root")
    if not (dst == ws_real or dst.startswith(ws_real + os.sep)):
        raise ValueError("Destination path escapes workspace root")
    if not os.path.isfile(src):
        raise FileNotFoundError(f"File not found: {old_path}")
    if os.path.exists(dst):
        raise ValueError(f"Destination already exists: {new_path}")

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    import shutil
    shutil.move(src, dst)
    return {"old_path": old_path, "new_path": new_path, "size": os.path.getsize(dst)}


def get_channel_workspace_index_prefix(channel_id: str) -> str:
    """Returns the file_path prefix for filesystem_chunks queries."""
    return f"channels/{channel_id}"
