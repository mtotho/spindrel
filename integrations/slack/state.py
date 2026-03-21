"""Per-channel bot preferences persisted to slack_state.json."""
import asyncio
import json
from pathlib import Path

from slack_settings import STATE_PATH, _get_channel_map, _get_default_bot

_channel_state: dict[str, dict] = {}
_channel_locks: dict[str, asyncio.Lock] = {}


def get_channel_lock(channel: str) -> asyncio.Lock:
    if channel not in _channel_locks:
        _channel_locks[channel] = asyncio.Lock()
    return _channel_locks[channel]


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
    return _get_channel_map().get(channel) or _get_default_bot()


def get_channel_state(channel: str) -> dict:
    if channel in _channel_state:
        state = _channel_state[channel].copy()
        # Strip any legacy session_id (sessions are now derived from client_id)
        state.pop("session_id", None)
        return state
    return {"bot_id": resolve_bot(channel)}


def set_channel_state(channel: str, *, bot_id=None) -> None:
    if channel not in _channel_state:
        _channel_state[channel] = {"bot_id": resolve_bot(channel)}
    if bot_id is not None:
        _channel_state[channel]["bot_id"] = bot_id
    # Remove legacy session_id if present
    _channel_state[channel].pop("session_id", None)
    _save_state()
