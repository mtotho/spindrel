"""Mission Control integration configuration — DB-backed with env var fallback."""
from __future__ import annotations

import os

from integrations.sdk import make_settings

_Base = make_settings("mission_control", {
    "MISSION_CONTROL_IMAGE": "mission-control:latest",
    "MISSION_CONTROL_CONTAINER_NAME": "mission-control",
    "AGENT_SERVER_URL": "http://host.docker.internal:8000",
})


class _Settings(_Base):
    @property
    def MISSION_CONTROL_PORT(self) -> int:
        return int(self._get("MISSION_CONTROL_PORT", "9100"))

    @property
    def WORKSPACE_ROOT(self) -> str:
        return self._get("WORKSPACE_ROOT", os.path.expanduser("~/.agent-workspaces"))

    @property
    def MISSION_CONTROL_DB_PATH(self) -> str:
        return self._get(
            "MISSION_CONTROL_DB_PATH",
            os.path.join(self.WORKSPACE_ROOT, "mission_control", "mc.db"),
        )


settings = _Settings()
