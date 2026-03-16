import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "agent-client"
CONFIG_FILE = CONFIG_DIR / "config.env"

_DEFAULTS = {
    "AGENT_URL": "http://localhost:8000",
    "API_KEY": "",
    "BOT_ID": "default",
    "TTS_ENABLED": "false",
    "PIPER_MODEL": "en_US-lessac-medium",
    "PIPER_MODEL_DIR": "~/.local/share/piper",
    "TTS_SPEED": "1.0",
    "LISTEN_SOUND": "chime",
    "WHISPER_MODEL": "base.en",
    "WAKE_WORDS": "",
}


@dataclass
class ClientConfig:
    agent_url: str = "http://localhost:8000"
    api_key: str = ""
    bot_id: str = "default"
    tts_enabled: bool = False
    piper_model: str = "en_US-lessac-medium"
    piper_model_dir: str = "~/.local/share/piper"
    tts_speed: float = 1.0
    listen_sound: str = "chime"
    whisper_model: str = "base.en"
    wake_words: list[str] | None = None


def load_config() -> ClientConfig:
    values = dict(_DEFAULTS)

    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, val = line.partition("=")
                    values[key.strip()] = val.strip()

    for key in _DEFAULTS:
        env_val = os.environ.get(key)
        if env_val is not None:
            values[key] = env_val

    try:
        tts_speed = float(values.get("TTS_SPEED", "1.0"))
    except ValueError:
        tts_speed = 1.0

    return ClientConfig(
        agent_url=values["AGENT_URL"].rstrip("/"),
        api_key=values["API_KEY"],
        bot_id=values["BOT_ID"],
        tts_enabled=values.get("TTS_ENABLED", "false").lower() in ("true", "1", "yes"),
        piper_model=values.get("PIPER_MODEL", "en_US-lessac-medium"),
        piper_model_dir=values.get("PIPER_MODEL_DIR", "~/.local/share/piper"),
        tts_speed=tts_speed,
        listen_sound=values.get("LISTEN_SOUND", "chime"),
        whisper_model=values.get("WHISPER_MODEL", "base.en"),
        wake_words=_parse_list(values.get("WAKE_WORDS", "")),
    )


def _parse_list(val: str) -> list[str] | None:
    items = [x.strip() for x in val.split(",") if x.strip()]
    return items if items else None
