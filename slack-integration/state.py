"""Per-channel bot/session preferences persisted to slack_state.json."""
import json
from pathlib import Path

from slack_settings import STATE_PATH, channel_map, default_bot

_channel_state: dict[str, dict] = {}
_OMIT = object()


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
        Path(STATE_PATH).write_text(json.dumps(_channel_state, indent=2))
    except OSError:
        pass


_load_state()


def resolve_bot(channel: str) -> str:
    return channel_map.get(channel) or default_bot


def get_channel_state(channel: str) -> dict:
    if channel in _channel_state:
        return _channel_state[channel].copy()
    return {"bot_id": resolve_bot(channel), "session_id": None}


def set_channel_state(channel: str, *, bot_id=None, session_id=_OMIT) -> None:
    if channel not in _channel_state:
        _channel_state[channel] = {"bot_id": resolve_bot(channel), "session_id": None}
    if bot_id is not None:
        _channel_state[channel]["bot_id"] = bot_id
    if session_id is not _OMIT:
        _channel_state[channel]["session_id"] = session_id
    _save_state()
