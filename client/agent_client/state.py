import json
import uuid
from pathlib import Path

STATE_DIR = Path.home() / ".config" / "agent-client"
STATE_FILE = STATE_DIR / "state.json"


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _save_state(data: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data))


def load_session_id() -> uuid.UUID:
    state = _load_state()
    if "session_id" in state:
        try:
            return uuid.UUID(state["session_id"])
        except ValueError:
            pass
    return new_session_id()


def new_session_id() -> uuid.UUID:
    sid = uuid.uuid4()
    save_session_id(sid)
    return sid


def save_session_id(sid: uuid.UUID) -> None:
    state = _load_state()
    state["session_id"] = str(sid)
    _save_state(state)


def load_bot_id() -> str | None:
    return _load_state().get("bot_id")


def save_bot_id(bot_id: str) -> None:
    state = _load_state()
    state["bot_id"] = bot_id
    _save_state(state)


def load_channel_id() -> str | None:
    return _load_state().get("channel_id")


def save_channel_id(channel_id: str | None) -> None:
    state = _load_state()
    if channel_id is None:
        state.pop("channel_id", None)
    else:
        state["channel_id"] = channel_id
    _save_state(state)


def load_model_override() -> str | None:
    return _load_state().get("model_override")


def save_model_override(model: str | None) -> None:
    state = _load_state()
    if model is None:
        state.pop("model_override", None)
    else:
        state["model_override"] = model
    _save_state(state)
