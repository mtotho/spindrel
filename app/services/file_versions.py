"""Shared `.versions` backup helpers for workspace-backed files."""
from __future__ import annotations

import glob
import logging
import os
import shutil
import time

logger = logging.getLogger(__name__)

MAX_BACKUP_VERSIONS_DEFAULT = 20
MAX_BACKUP_VERSIONS_DATA = 50
DATA_FILE_EXTS = {".json", ".yaml", ".yml", ".toml"}


def retention_for_path(path: str) -> int:
    ext = os.path.splitext(path)[1].lower()
    return MAX_BACKUP_VERSIONS_DATA if ext in DATA_FILE_EXTS else MAX_BACKUP_VERSIONS_DEFAULT


def save_file_backup(path: str) -> str | None:
    """Save *path* into a sibling `.versions` directory and prune old copies."""
    if not os.path.isfile(path):
        return None

    parent = os.path.dirname(path)
    basename = os.path.basename(path)
    versions_dir = os.path.join(parent, ".versions")
    os.makedirs(versions_dir, exist_ok=True)

    ts = f"{time.time():.4f}".replace(".", "-")
    backup_path = os.path.join(versions_dir, f"{basename}.{ts}.bak")

    try:
        shutil.copy2(path, backup_path)
    except OSError:
        logger.warning("Failed to create backup of %s", path, exc_info=True)
        return None

    pattern = os.path.join(versions_dir, f"{basename}.*.bak")
    backups = sorted(glob.glob(pattern), key=lambda p: (os.path.getmtime(p), p), reverse=True)
    for old in backups[retention_for_path(path):]:
        try:
            os.remove(old)
        except OSError:
            logger.debug("Failed to prune old backup %s", old, exc_info=True)

    return backup_path


def list_file_versions(path: str) -> list[dict]:
    parent = os.path.dirname(path)
    basename = os.path.basename(path)
    versions_dir = os.path.join(parent, ".versions")
    if not os.path.isdir(versions_dir):
        return []

    pattern = os.path.join(versions_dir, f"{basename}.*.bak")
    backups = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    versions: list[dict] = []
    for backup_path in backups:
        try:
            st = os.stat(backup_path)
        except OSError:
            continue
        versions.append({
            "version": os.path.basename(backup_path),
            "bytes": st.st_size,
            "modified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(st.st_mtime)),
        })
    return versions


def restore_file_version(path: str, version: str) -> str | None:
    """Restore *version* over *path*, backing up the current live file first."""
    if "/" in version or ".." in version:
        raise ValueError("version must be a plain filename")

    parent = os.path.dirname(path)
    basename = os.path.basename(path)
    if not version.startswith(basename + "."):
        raise ValueError(f"Backup does not belong to {basename}")

    backup_path = os.path.join(parent, ".versions", version)
    if not os.path.isfile(backup_path):
        raise FileNotFoundError("Backup not found")

    prior_backup = save_file_backup(path) if os.path.isfile(path) else None
    shutil.copy2(backup_path, path)
    return os.path.basename(prior_backup) if prior_backup else None
