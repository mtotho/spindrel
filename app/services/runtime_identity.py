"""Runtime/build identity for health and agent preflight checks."""
from __future__ import annotations

import os
import socket
import time
from datetime import datetime, timezone

from app.config import VERSION

_STARTED_AT = datetime.now(timezone.utc)
_START_MONOTONIC = time.monotonic()


def _clean_env(name: str) -> str | None:
    value = (os.environ.get(name) or "").strip()
    if not value or value.lower() in {"unknown", "none", "null"}:
        return None
    return value


def _hostname() -> str | None:
    try:
        value = socket.gethostname().strip()
    except Exception:
        return None
    return value or None


def _container_id(hostname: str | None) -> str | None:
    if not hostname:
        return None
    # Docker defaults the hostname to the short container id. Keep this
    # deliberately conservative; do not read the Docker socket from the app.
    if len(hostname) >= 12 and all(ch in "0123456789abcdef" for ch in hostname.lower()):
        return hostname
    return None


def runtime_identity() -> dict:
    """Return safe, agent-readable process and build identity."""
    hostname = _hostname()
    return {
        "status": "ok",
        "version": VERSION,
        "process": {
            "started_at": _STARTED_AT.isoformat(),
            "uptime_seconds": int(time.monotonic() - _START_MONOTONIC),
            "hostname": hostname,
            "container_id": _container_id(hostname),
        },
        "build": {
            "commit_sha": _clean_env("SPINDREL_BUILD_SHA"),
            "ref": _clean_env("SPINDREL_BUILD_REF"),
            "built_at": _clean_env("SPINDREL_BUILD_TIME"),
            "source": _clean_env("SPINDREL_BUILD_SOURCE"),
            "deploy_id": _clean_env("SPINDREL_DEPLOY_ID"),
        },
        "features": {
            "recent_errors_review_state": True,
        },
    }
