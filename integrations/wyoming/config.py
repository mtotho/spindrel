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


def _in_docker() -> bool:
    return os.path.exists("/.dockerenv")


def _instance_id() -> str:
    try:
        from app.config import settings as _s
        if _s.SPINDREL_INSTANCE_ID:
            return _s.SPINDREL_INSTANCE_ID
    except Exception:
        pass
    return os.environ.get("SPINDREL_INSTANCE_ID", "").strip() or "default"


def _default_whisper_uri() -> str:
    return f"tcp://whisper-{_instance_id()}:10300" if _in_docker() else "tcp://localhost:10300"


def _default_piper_uri() -> str:
    return f"tcp://piper-{_instance_id()}:10200" if _in_docker() else "tcp://localhost:10200"


WHISPER_URI = _setting("WYOMING_WHISPER_URI", _default_whisper_uri())
PIPER_URI = _setting("WYOMING_PIPER_URI", _default_piper_uri())
DEFAULT_VOICE = _setting("WYOMING_DEFAULT_VOICE", "en_US-lessac-medium")
API_KEY = _setting("AGENT_API_KEY", os.environ.get("API_KEY", ""))
AGENT_BASE_URL = _setting("AGENT_BASE_URL", os.environ.get("AGENT_BASE_URL", "http://localhost:8000"))

# ESPHome bridge settings
ESPHOME_API_PASSWORD = _setting("ESPHOME_API_PASSWORD", "")
