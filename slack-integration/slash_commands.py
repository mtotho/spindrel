"""Slash commands: /bot, /sessions, /session, /bots."""
import uuid

from agent_client import fetch_sessions, list_bots
from formatting import format_last_active
from session_helpers import fuzzy_find_session, slack_client_id
from state import get_channel_state, set_channel_state


def register_slash_commands(app):
    @app.command("/bot")
    async def cmd_bot(ack, command, respond):
        await ack()
        channel = command.get("channel_id") or ""
        arg = (command.get("text") or "").strip()

        if not arg:
            state = get_channel_state(channel)
            await respond(f"Current bot: `{state['bot_id']}`")
            return

        valid = {b["id"] for b in await list_bots()}

        if arg not in valid:
            await respond(f"Unknown bot. Available: {', '.join(sorted(valid))}")
            return

        set_channel_state(channel, bot_id=arg, session_id=None)
        await respond(f"Switched to `{arg}`. New session for this bot.")

    @app.command("/sessions")
    async def cmd_sessions(ack, command, respond):
        await ack()
        channel = command.get("channel_id") or ""
        state = get_channel_state(channel)
        client_id = slack_client_id(channel)
        bot_id = state["bot_id"]

        current_sid = (
            state.get("session_id") or str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{client_id}:{bot_id}"))
        ).lower()

        try:
            sessions = await fetch_sessions(channel)
        except Exception as e:
            await respond(f"Error listing sessions: {e}")
            return

        if not sessions:
            await respond("No sessions. Send a message to create one, or `/session new`.")
            return

        lines = []
        for i, s in enumerate(sessions[:25], 1):
            sid = s.get("id") or ""
            selected = sid.lower() == current_sid if sid else False
            marker = "[*] " if selected else "    "
            title = (s.get("title") or "(untitled)")[:28]
            last = format_last_active(s.get("last_active") or "")
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
        channel = command.get("channel_id") or ""
        arg = (command.get("text") or "").strip()

        state = get_channel_state(channel)
        client_id = slack_client_id(channel)
        default_sid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{client_id}:{state['bot_id']}"))

        if not arg:
            sid = state.get("session_id") or default_sid
            await respond(f"Current session: `{sid[:8]}...`")
            return

        if arg.lower() == "new":
            set_channel_state(channel, session_id=str(uuid.uuid4()))
            await respond("Started a new session.")
            return

        try:
            sessions = await fetch_sessions(channel)
        except Exception as e:
            await respond(f"Error: {e}")
            return

        if arg.isdigit():
            index = int(arg) - 1
            if 0 <= index < len(sessions):
                sid = sessions[index]["id"]
                set_channel_state(channel, session_id=sid)
                title = sessions[index].get("title") or "(untitled)"
                await respond(f"✓ Switched to session `{sid[:8]}...` {title}")
            else:
                await respond("Invalid session number. Use `/sessions` to list.")
            return

        try:
            sid_parsed = str(uuid.UUID(arg))
            found = any((s.get("id") or "").lower() == sid_parsed.lower() for s in sessions)
            if found:
                set_channel_state(channel, session_id=sid_parsed)
                await respond(f"Switched to session `{sid_parsed[:8]}...`")
            else:
                await respond("Session with that UUID not found for this client.")
            return
        except ValueError:
            pass

        found = fuzzy_find_session(sessions, arg)
        if found:
            sid = found["id"]
            set_channel_state(channel, session_id=sid)
            title = found.get("title") or "(untitled)"
            await respond(f"Switched to session `{sid[:8]}...` ({title})")
        else:
            await respond("No session found matching that number, id, or title. Use `/sessions` to list.")

    @app.command("/bots")
    async def cmd_bots(ack, command, respond):
        await ack()
        channel = command.get("channel_id") or ""
        bots_list = await list_bots()
        current = get_channel_state(channel)["bot_id"]
        lines = [
            f"{'*' if b['id'] == current else ' '} `{b['id']}` — {b['name']} ({b['model']})"
            for b in bots_list
        ]
        await respond("\n".join(lines))
