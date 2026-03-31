"""Mission Control integration configuration — DB-backed with env var fallback."""
from __future__ import annotations

import os


def _get(key: str, default: str = "") -> str:
    """Get a config value: DB cache > env var > default."""
    try:
        from app.services.integration_settings import get_value
        return get_value("mission-control", key, default)
    except ImportError:
        return os.environ.get(key, default)


class _Settings:
    @property
    def MISSION_CONTROL_IMAGE(self) -> str:
        return _get("MISSION_CONTROL_IMAGE", "mission-control:latest")

    @property
    def MISSION_CONTROL_PORT(self) -> int:
        return int(_get("MISSION_CONTROL_PORT", "9100"))

    @property
    def MISSION_CONTROL_CONTAINER_NAME(self) -> str:
        return _get("MISSION_CONTROL_CONTAINER_NAME", "mission-control")

    @property
    def WORKSPACE_ROOT(self) -> str:
        return _get("WORKSPACE_ROOT", os.path.expanduser("~/.agent-workspaces"))

    @property
    def AGENT_SERVER_URL(self) -> str:
        return _get("AGENT_SERVER_URL", "http://host.docker.internal:8000")


settings = _Settings()
