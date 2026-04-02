"""Path translation for sibling container pattern.

When the server runs inside Docker, workspace files are accessed via a mounted
volume (WORKSPACE_LOCAL_DIR), but child containers need the host-side path
(WORKSPACE_HOST_DIR) for their ``docker -v`` bind mounts.

When neither env var is set (host-based dev), both helpers return the same
value and ``local_to_host`` is a no-op.
"""

import os

from app.config import settings


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


def local_to_host(path: str) -> str:
    """Translate a local workspace path to its host equivalent.

    Non-workspace paths pass through unchanged.
    """
    local_base = local_workspace_base()
    host_base = host_workspace_base()
    if local_base == host_base:
        return path
    if path == local_base:
        return host_base
    if path.startswith(local_base + os.sep):
        return host_base + path[len(local_base):]
    return path
