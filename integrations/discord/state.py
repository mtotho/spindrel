"""Per-channel bot preferences persisted to discord_state.json."""
import json
import tempfile
from pathlib import Path

from discord_settings import STATE_PATH, _get_channel_map, _get_default_bot

_channel_state: dict[str, dict] = {}


def _load_state() -> None:
    global _channel_state
    path = Path(STATE_PATH)
    if path.is_file():
        try:
            data = json.loads(path.read_text())
            _channel_state = {k: v for k, v in data.items() if isinstance(v, dict)}
        except (json.JSONDecodeError, OSError):
            _channel_state = {}
    else:
        _channel_state = {}


def _save_state() -> None:
    try:
        path = Path(STATE_PATH)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with open(fd, "w") as f:
                json.dump(_channel_state, f, indent=2)
            Path(tmp).replace(path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    except OSError:
        pass


_load_state()


def resolve_bot(channel: str) -> str:
    return _get_channel_map().get(channel) or _get_default_bot()


def get_channel_state(channel: str) -> dict:
    if channel in _channel_state:
        state = _channel_state[channel].copy()
        state.pop("session_id", None)
        return state
    return {"bot_id": resolve_bot(channel)}


def set_channel_state(channel: str, *, bot_id=None) -> None:
    if channel not in _channel_state:
        _channel_state[channel] = {"bot_id": resolve_bot(channel)}
    if bot_id is not None:
        _channel_state[channel]["bot_id"] = bot_id
    _channel_state[channel].pop("session_id", None)
    _save_state()


# ---------------------------------------------------------------------------
# Global settings (stored under "__settings__" key in discord_state.json)
# ---------------------------------------------------------------------------

def get_global_setting(key: str, default=None):
    """Read a global Discord integration setting."""
    return _channel_state.get("__settings__", {}).get(key, default)


def set_global_setting(key: str, value) -> None:
    """Write a global Discord integration setting."""
    if "__settings__" not in _channel_state:
        _channel_state["__settings__"] = {}
    if value is None:
        _channel_state["__settings__"].pop(key, None)
    else:
        _channel_state["__settings__"][key] = value
    _save_state()
