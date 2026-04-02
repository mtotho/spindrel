"""Workspace disk usage reporting."""
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from app.services.paths import local_workspace_base


def _dir_stats(path: str) -> dict:
    """Walk a directory and return total bytes + file count (sync)."""
    total = 0
    count = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                    count += 1
                except OSError:
                    pass
    except OSError:
        pass
    return {"total_bytes": total, "file_count": count}


def _get_filesystem_usage(base: str) -> dict:
    """shutil.disk_usage on the workspace partition."""
    usage = shutil.disk_usage(base)
    return {
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "usage_percent": round(usage.used / usage.total * 100, 1) if usage.total else 0,
    }


def _get_workspace_sizes(base: str) -> tuple[int, list[dict]]:
    """Walk workspace dirs and return (total_bytes, workspace_list)."""
    workspaces: list[dict] = []
    total = 0

    base_path = Path(base)
    if not base_path.is_dir():
        return 0, []

    # shared/ directory
    shared = base_path / "shared"
    if shared.is_dir():
        stats = _dir_stats(str(shared))
        subdirs = {}
        for sub in ("bots", "common", "users"):
            sub_path = shared / sub
            if sub_path.is_dir():
                subdirs[sub] = _dir_stats(str(sub_path))["total_bytes"]
        workspaces.append({
            "type": "shared",
            "id": "shared",
            "name": "shared",
            "path": str(shared),
            "total_bytes": stats["total_bytes"],
            "file_count": stats["file_count"],
            "subdirs": subdirs,
        })
        total += stats["total_bytes"]

    # Top-level bot directories (everything except shared/)
    try:
        for entry in sorted(base_path.iterdir()):
            if not entry.is_dir() or entry.name == "shared":
                continue
            stats = _dir_stats(str(entry))
            workspaces.append({
                "type": "bot",
                "id": entry.name,
                "name": entry.name,
                "path": str(entry),
                "total_bytes": stats["total_bytes"],
                "file_count": stats["file_count"],
            })
            total += stats["total_bytes"]
    except OSError:
        pass

    # Sort by size descending
    workspaces.sort(key=lambda w: w["total_bytes"], reverse=True)
    return total, workspaces


def _get_full_disk_report() -> dict:
    """Combine filesystem usage + per-workspace sizes."""
    base = local_workspace_base()
    fs = _get_filesystem_usage(base)
    ws_total, workspaces = _get_workspace_sizes(base)
    return {
        "filesystem": fs,
        "workspace_base_dir": base,
        "workspace_total_bytes": ws_total,
        "workspaces": workspaces,
    }


async def get_full_disk_report() -> dict:
    """Async wrapper — runs blocking I/O in a thread."""
    return await asyncio.to_thread(_get_full_disk_report)
