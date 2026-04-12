"""Wyoming integration config -- reads settings from DB or environment."""
from __future__ import annotations

import os


def _setting(key: str, default: str = "") -> str:
    """Read an integration setting from the DB-backed manifest, falling back to env."""
    try:
        from app.services.integration_manifests import get_setting_value
        val = get_setting_value("wyoming", key)
        if val is not None:
            return val
    except Exception:
        pass
    return os.environ.get(key, default)


WHISPER_URI = _setting("WYOMING_WHISPER_URI", "tcp://localhost:10300")
PIPER_URI = _setting("WYOMING_PIPER_URI", "tcp://localhost:10200")
DEFAULT_VOICE = _setting("WYOMING_DEFAULT_VOICE", "en_US-lessac-medium")
API_KEY = _setting("AGENT_API_KEY", os.environ.get("API_KEY", ""))
AGENT_BASE_URL = _setting("AGENT_BASE_URL", os.environ.get("AGENT_BASE_URL", "http://localhost:8000"))
