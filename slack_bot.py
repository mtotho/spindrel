"""
Slack Socket Mode bot: routes Slack messages to the agent server POST /chat.
Runs as a separate process; no inbound ports. Configure via slack_config.yaml and env.
"""
import asyncio
import json
import os
import re
import uuid
import yaml
from datetime import datetime, timezone
import httpx
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]  # xoxb-...
APP_LEVEL_TOKEN = os.environ["SLACK_APP_TOKEN"]  # xapp-...
API_KEY = os.environ.get("AGENT_API_KEY") or os.environ.get("API_KEY")
AGENT_BASE_URL = os.environ.get("AGENT_BASE_URL", "http://localhost:8000")

_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "slack_config.yaml")
with open(_config_path) as f:
    cfg = yaml.safe_load(f) or {}

channel_map: dict[str, str] = cfg.get("channels", {})
user_map: dict[str, str] = cfg.get("users", {})
default_bot: str = cfg.get("default_bot", "default")
session_scope: str = cfg.get("session_scope", "user")

app = AsyncApp(token=BOT_TOKEN)
http = httpx.AsyncClient()

# Per-user state for slash commands: bot_id override, session_id override (None = use deterministic)
# Persisted to JSON so it survives restarts.
_STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "slack_state.json")
_user_state: dict[str, dict] = {}
_OMIT = object()


def _load_state() -> None:
    global _user_state
    if os.path.isfile(_STATE_PATH):
        try:
            with open(_STATE_PATH) as f:
                data = json.load(f)
            _user_state = {k: v for k, v in data.items() if isinstance(v, dict)}
        except (json.JSONDecodeError, OSError):
            _user_state = {}


def _save_state() -> None:
    try:
        with open(_STATE_PATH, "w") as f:
            json.dump(_user_state, f, indent=2)
    except OSError:
        pass


_load_state()


def resolve_bot(channel: str, user: str) -> str:
    # priority: user config → channel config → default
    return user_map.get(user) or channel_map.get(channel) or default_bot


def get_user_state(user_id: str, channel: str | None = None) -> dict:
    """Current bot_id and session_id override. channel used for default bot when no state."""
    if user_id in _user_state:
        return _user_state[user_id].copy()
    bot_id = resolve_bot(channel or "", user_id) if channel else default_bot
    return {"bot_id": bot_id, "session_id": None}


def set_user_state(user_id: str, *, bot_id=None, session_id=_OMIT) -> None:
    """Update user state. Pass session_id=None to clear session override."""
    if user_id not in _user_state:
        _user_state[user_id] = {"bot_id": resolve_bot("", user_id), "session_id": None}
    if bot_id is not None:
        _user_state[user_id]["bot_id"] = bot_id
    if session_id is not _OMIT:
        _user_state[user_id]["session_id"] = session_id
    _save_state()


def _slack_client_id(user_id: str, channel_id: str) -> str:
    """Same client_id as used in dispatch (for listing sessions)."""
    return f"slack:{user_id if session_scope == 'user' else channel_id}"


def _format_last_active(raw: str) -> str:
    """Turn an ISO timestamp into a short relative time for Slack."""
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - dt
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "just now"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        if days < 30:
            return f"{days}d ago"
        return dt.strftime("%b %d")
    except (ValueError, TypeError):
        return (raw or "")[:16]


async def _fetch_sessions(user_id: str, channel_id: str) -> list[dict]:
    """GET /sessions?client_id=... for this Slack user/channel."""
    client_id = _slack_client_id(user_id, channel_id)
    r = await http.get(
        f"{AGENT_BASE_URL}/sessions",
        params={"client_id": client_id},
        headers={"Authorization": f"Bearer {API_KEY}"},
    )
    r.raise_for_status()
    return r.json()


def _fuzzy_find_session(sessions: list[dict], query: str) -> dict | None:
    """Match by UUID prefix or title (single match), or None."""
    if not query or not sessions:
        return None
    query = query.strip().lower()
    by_id = [s for s in sessions if (s.get("id") or "").lower().startswith(query)]
    if len(by_id) == 1:
        return by_id[0]
    by_title = [s for s in sessions if query in (s.get("title") or "").lower()]
    if len(by_title) == 1:
        return by_title[0]
    if by_id or by_title:
        return (by_id + [m for m in by_title if m not in by_id])[0]
    return None


def format_response_for_slack(response: str) -> str:
    """Replace [silent]...[/silent] with italicized muted indicator so it's visible but distinct."""
    if not response or not response.strip():
        return "_(no response)_"
    # Replace each [silent]...[/silent] with _🔇 inner_
    formatted = re.sub(
        r"\[silent\](.*?)\[/silent\]",
        lambda m: f"_🔇 {m.group(1).strip()}_",
        response,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return formatted.strip()


async def dispatch(channel: str, user: str, text: str, say):
    text = (text or "").strip()
    if not text:
        await say("_No message to process._")
        return

    state = get_user_state(user, channel)
    bot_id = state["bot_id"]
    client_id = f"slack:{user if session_scope == 'user' else channel}"
    # Use override from /session, or deterministic session for this client+bot
    session_id_override = state.get("session_id")
    if session_id_override is not None:
        session_id = session_id_override
    else:
        session_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"slack:{client_id}:{bot_id}"))

    try:
        r = await http.post(
            f"{AGENT_BASE_URL}/chat",
            json={
                "message": text,
                "bot_id": bot_id,
                "client_id": client_id,
                "session_id": session_id,
            },
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=120,
        )
        r.raise_for_status()
        body = r.json()
        reply = (body.get("response") or "").strip()
        await say(format_response_for_slack(reply))
    except Exception as e:
        await say(f"Error: {str(e)[:500]}")
        return


@app.event("message")
async def on_message(event, say):
    if event.get("subtype"):  # ignore edits, bot messages, joins, etc.
        return
    if event.get("bot_id"):  # ignore our own and other bots' messages
        return
    if (event.get("text") or "").strip().startswith("<@"):  # mention → handled by on_mention
        return
    await dispatch(event["channel"], event["user"], event.get("text", ""), say)


@app.event("app_mention")
async def on_mention(event, say):
    if event.get("bot_id"):
        return
    text = (event.get("text") or "").split(">", 1)[-1].strip()  # strip @mention prefix
    if not text:
        await say("_Say something after the mention._")
        return
    await dispatch(event["channel"], event["user"], text, say)


# ----- Slash commands -----


@app.command("/bot")
async def cmd_bot(ack, command, respond):
    await ack()
    user = command["user_id"]
    channel = command.get("channel_id") or ""
    arg = (command.get("text") or "").strip()

    if not arg:
        state = get_user_state(user, channel)
        await respond(f"Current bot: `{state['bot_id']}`")
        return

    r = await http.get(f"{AGENT_BASE_URL}/bots", headers={"Authorization": f"Bearer {API_KEY}"})
    r.raise_for_status()
    valid = {b["id"] for b in r.json()}

    if arg not in valid:
        await respond(f"Unknown bot. Available: {', '.join(sorted(valid))}")
        return

    set_user_state(user, bot_id=arg, session_id=None)  # reset to deterministic session for new bot
    await respond(f"Switched to `{arg}`. New session for this bot.")


@app.command("/sessions")
async def cmd_sessions(ack, command, respond):
    await ack()
    user = command["user_id"]
    channel = command.get("channel_id") or ""
    state = get_user_state(user, channel)
    current_sid = (state.get("session_id") or str(
        uuid.uuid5(uuid.NAMESPACE_DNS, f"slack:{_slack_client_id(user, channel)}:{state['bot_id']}")
    )).lower()

    try:
        sessions = await _fetch_sessions(user, channel)
    except Exception as e:
        await respond(f"Error listing sessions: {e}")
        return

    if not sessions:
        await respond("No sessions. Send a message to create one, or `/session new`.")
        return

    lines = []
    for i, s in enumerate(sessions[:25], 1):
        sid = (s.get("id") or "")
        selected = sid.lower() == current_sid if sid else False
        marker = "[*] " if selected else "    "
        title = (s.get("title") or "(untitled)")[:28]
        last = _format_last_active(s.get("last_active") or "")
        line = f"{marker}{i}. `{sid[:8]}` {title} bot=`{s.get('bot_id', '')}` {last}"
        lines.append(line)
    if len(sessions) > 25:
        lines.append(f"_... and {len(sessions) - 25} more_")
    lines.append("")
    lines.append("_Select: /session <number or id or title>_")
    await respond("\n".join(lines))


@app.command("/session")
async def cmd_session(ack, command, respond):
    await ack()
    user = command["user_id"]
    channel = command.get("channel_id") or ""
    arg = (command.get("text") or "").strip()

    state = get_user_state(user, channel)
    client_id = _slack_client_id(user, channel)
    default_sid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"slack:{client_id}:{state['bot_id']}"))

    if not arg:
        sid = state.get("session_id") or default_sid
        await respond(f"Current session: `{sid[:8]}...`")
        return

    if arg.lower() == "new":
        set_user_state(user, session_id=str(uuid.uuid4()))
        await respond("Started a new session.")
        return

    try:
        sessions = await _fetch_sessions(user, channel)
    except Exception as e:
        await respond(f"Error: {e}")
        return

    # By 1-based index
    if arg.isdigit():
        index = int(arg) - 1
        if 0 <= index < len(sessions):
            sid = sessions[index]["id"]
            set_user_state(user, session_id=sid)
            title = sessions[index].get("title") or "(untitled)"
            await respond(f"✓ Switched to session `{sid[:8]}...` {title}")
        else:
            await respond("Invalid session number. Use `/sessions` to list.")
        return

    # By full UUID (must be in list)
    try:
        sid_parsed = str(uuid.UUID(arg))
        found = any((s.get("id") or "").lower() == sid_parsed.lower() for s in sessions)
        if found:
            set_user_state(user, session_id=sid_parsed)
            await respond(f"Switched to session `{sid_parsed[:8]}...`")
        else:
            await respond("Session with that UUID not found for this client.")
        return
    except ValueError:
        pass

    # Fuzzy: prefix or title
    found = _fuzzy_find_session(sessions, arg)
    if found:
        sid = found["id"]
        set_user_state(user, session_id=sid)
        title = found.get("title") or "(untitled)"
        await respond(f"Switched to session `{sid[:8]}...` ({title})")
    else:
        await respond("No session found matching that number, id, or title. Use `/sessions` to list.")


@app.command("/bots")
async def cmd_bots(ack, command, respond):
    await ack()
    user = command["user_id"]
    channel = command.get("channel_id") or ""
    r = await http.get(f"{AGENT_BASE_URL}/bots", headers={"Authorization": f"Bearer {API_KEY}"})
    r.raise_for_status()
    bots_list = r.json()
    current = get_user_state(user, channel)["bot_id"]
    lines = [
        f"{'*' if b['id'] == current else ' '} `{b['id']}` — {b['name']} ({b['model']})"
        for b in bots_list
    ]
    await respond("\n".join(lines))


async def main():
    handler = AsyncSocketModeHandler(app, APP_LEVEL_TOKEN)
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
