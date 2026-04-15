"""Path translation and integration directory discovery.

When the server runs inside Docker, workspace files and the Spindrel home
directory are accessed via mounted volumes.  Child containers need the
host-side paths for their ``docker -v`` bind mounts.

When neither env var pair is set (host-based dev), both helpers return the
same value and translations are no-ops.
"""

import logging
import os
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Runtime integration dirs (appended at startup, e.g. workspace integrations)
# ---------------------------------------------------------------------------

_runtime_integration_dirs: list[str] = []


def add_runtime_integration_dir(path: str) -> None:
    """Register an integration directory discovered at runtime."""
    if path not in _runtime_integration_dirs:
        _runtime_integration_dirs.append(path)


# ---------------------------------------------------------------------------
# Workspace path helpers
# ---------------------------------------------------------------------------

def local_workspace_base() -> str:
    """Server-side workspace root (for file I/O)."""
    if settings.WORKSPACE_LOCAL_DIR:
        return settings.WORKSPACE_LOCAL_DIR
    return os.path.expanduser(settings.WORKSPACE_BASE_DIR)


def host_workspace_base() -> str:
    """Host-side workspace root (for docker -v mount args)."""
    if settings.WORKSPACE_HOST_DIR:
        return settings.WORKSPACE_HOST_DIR
    return os.path.expanduser(settings.WORKSPACE_BASE_DIR)


# ---------------------------------------------------------------------------
# Home directory helpers
# ---------------------------------------------------------------------------

def local_home_dir() -> str | None:
    """Container-local path to the Spindrel home directory, or None."""
    # Docker mode: HOME_LOCAL_DIR is the mount point
    if settings.HOME_LOCAL_DIR:
        return settings.HOME_LOCAL_DIR
    # Host mode: SPINDREL_HOME is the direct path
    if settings.SPINDREL_HOME:
        return os.path.expanduser(settings.SPINDREL_HOME)
    return None


def host_home_dir() -> str | None:
    """Host-side path to the Spindrel home directory, or None."""
    if settings.HOME_HOST_DIR:
        return settings.HOME_HOST_DIR
    if settings.SPINDREL_HOME:
        return os.path.expanduser(settings.SPINDREL_HOME)
    return None


# ---------------------------------------------------------------------------
# Path translation (host ↔ local)
# ---------------------------------------------------------------------------

def _host_local_mappings() -> list[tuple[str, str]]:
    """Return all (host_path, local_path) translation pairs."""
    mappings = []
    # Workspace paths
    mappings.append((host_workspace_base(), local_workspace_base()))
    # Spindrel home directory
    hh = host_home_dir()
    lh = local_home_dir()
    if hh and lh and hh != lh:
        mappings.append((hh, lh))
    return mappings


def local_to_host(path: str) -> str:
    """Translate a local path to its host equivalent.

    Non-mapped paths pass through unchanged.
    """
    for host_base, local_base in _host_local_mappings():
        if local_base == host_base:
            continue
        # Match on local_base, return host_base
        if path == local_base:
            return host_base
        if path.startswith(local_base + os.sep):
            return host_base + path[len(local_base):]
    return path


def host_to_local(path: str) -> str:
    """Translate a host-side path to its local (container) equivalent.

    Checks all known host→local mappings (workspace, home dir).
    Non-mapped paths pass through unchanged.
    """
    for host_base, local_base in _host_local_mappings():
        if local_base == host_base:
            continue
        if path == host_base:
            return local_base
        if path.startswith(host_base + os.sep):
            return local_base + path[len(host_base):]
    return path


# ---------------------------------------------------------------------------
# Integration directory discovery
# ---------------------------------------------------------------------------

def effective_integration_dirs() -> list[str]:
    """All external integration base directories (local/container-side paths).

    Sources (in priority order):
    1. SPINDREL_HOME / HOME_LOCAL_DIR
    2. Legacy INTEGRATION_DIRS (translated via host_to_local)
    3. Runtime-added dirs (e.g. workspace integrations)

    Each returned path is a directory whose subdirectories are integrations.
    """
    seen: set[str] = set()
    dirs: list[str] = []

    def _add(p: str) -> None:
        resolved = os.path.realpath(os.path.expanduser(p))
        if resolved in seen:
            return
        seen.add(resolved)
        if os.path.isdir(resolved):
            dirs.append(resolved)
        else:
            logger.warning("Integration directory does not exist: %s", resolved)

    # 1. Spindrel home
    home = local_home_dir()
    if home:
        _add(home)

    # 2. Legacy INTEGRATION_DIRS (host paths → translated)
    legacy = settings.INTEGRATION_DIRS
    if legacy:
        for p in legacy.split(":"):
            p = p.strip()
            if p:
                _add(host_to_local(p))

    # 3. Runtime dirs (workspace integrations, etc.)
    for p in _runtime_integration_dirs:
        _add(p)

    return dirs
