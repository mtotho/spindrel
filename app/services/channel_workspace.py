"""Channel workspace service — resolves paths and performs file ops for channel workspaces.

Channel workspaces live inside the shared workspace (or bot workspace) at:
  {ws_root}/channels/{channel_id}/workspace/
  {ws_root}/channels/{channel_id}/workspace/archive/
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.bots import BotConfig

logger = logging.getLogger(__name__)


def _get_ws_root(bot: "BotConfig") -> str:
    """Get the workspace root for channel workspaces.

    For shared workspace bots, uses the shared workspace root.
    For standalone bots, uses the individual workspace root.
    """
    if bot.shared_workspace_id:
        from app.services.shared_workspace import shared_workspace_service
        return shared_workspace_service.get_host_root(bot.shared_workspace_id)
    from app.services.workspace import workspace_service
    return workspace_service.get_workspace_root(bot.id, bot)


def get_channel_workspace_root(channel_id: str, bot: "BotConfig") -> str:
    """Returns {ws_root}/channels/{channel_id}/workspace/"""
    ws_root = _get_ws_root(bot)
    return os.path.join(ws_root, "channels", channel_id, "workspace")


def get_channel_archive_root(channel_id: str, bot: "BotConfig") -> str:
    """Returns {ws_root}/channels/{channel_id}/workspace/archive/"""
    return os.path.join(get_channel_workspace_root(channel_id, bot), "archive")


def ensure_channel_workspace(
    channel_id: str,
    bot: "BotConfig",
    *,
    display_name: str | None = None,
) -> str:
    """Create workspace/ + archive/ + data/ dirs, idempotent. Returns workspace root."""
    ws_path = get_channel_workspace_root(channel_id, bot)
    for subdir in ("archive", "data"):
        os.makedirs(os.path.join(ws_path, subdir), exist_ok=True)

    # Write/update .channel_info so humans can identify UUID folders
    label = display_name or channel_id
    info_content = f"channel_id: {channel_id}\ndisplay_name: {label}\n"
    # Write at both levels: channels/{id}/ and channels/{id}/workspace/
    for info_dir in (os.path.dirname(ws_path), ws_path):
        info_path = os.path.join(info_dir, ".channel_info")
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
            for entry in sorted(os.scandir(data_path), key=lambda e: e.name):
                if entry.is_file():
                    stat = entry.stat()
                    files.append({
                        "name": entry.name,
                        "path": f"data/{entry.name}",
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
    target = os.path.normpath(os.path.join(ws_real, path))
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


def get_channel_workspace_index_prefix(channel_id: str) -> str:
    """Returns the file_path prefix for filesystem_chunks queries."""
    return f"channels/{channel_id}/workspace"
