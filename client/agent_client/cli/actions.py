"""Server-driven client actions (new_session, switch_bot, etc.)."""
import uuid

import httpx

from agent_client.client import AgentClient
from agent_client.state import new_session_id, save_bot_id, save_session_id

from agent_client.cli.display import format_last_active
from agent_client.cli.voice import apply_bot_audio


def handle_client_actions(actions: list[dict], client: AgentClient, ctx: dict) -> None:
    """Execute client-side actions returned by the server."""
    for action_info in actions:
        action = action_info.get("action")
        params = action_info.get("params", {})

        if action == "new_session":
            ctx["session_id"] = new_session_id()
            print(f"  [action] New session: {ctx['session_id']}")

        elif action == "switch_bot":
            bot_id = params.get("bot_id")
            if bot_id:
                ctx["bot_id"] = bot_id
                save_bot_id(bot_id)
                apply_bot_audio(client, ctx)
                print(f"  [action] Switched bot to: {bot_id}")
            else:
                print("  [action] switch_bot missing bot_id param")

        elif action == "switch_session":
            raw = params.get("session_id")
            if raw:
                try:
                    sid = uuid.UUID(raw)
                    ctx["session_id"] = sid
                    save_session_id(sid)
                    print(f"  [action] Switched to session: {sid}")
                except ValueError:
                    print(f"  [action] Invalid session UUID: {raw}")
            else:
                print("  [action] switch_session missing session_id param")

        elif action == "toggle_tts":
            ctx["tts"] = not ctx["tts"]
            state = "on" if ctx["tts"] else "off"
            print(f"  [action] TTS {state}")

        elif action == "list_sessions":
            try:
                sessions = client.list_sessions()
                if not sessions:
                    print("  [action] No sessions.")
                else:
                    for s in sessions:
                        active = " *" if str(ctx["session_id"]) == s["id"] else ""
                        title = s.get("title") or "(untitled)"
                        last = format_last_active(s.get("last_active", ""))
                        print(f"  {s['id'][:8]}  {title}  bot={s['bot_id']}  {last}{active}")
            except httpx.HTTPError as e:
                print(f"  [action] Error listing sessions: {e}")

        elif action == "list_bots":
            try:
                bots = client.list_bots()
                if not bots:
                    print("  [action] No bots configured.")
                else:
                    for b in bots:
                        active = " *" if ctx["bot_id"] == b["id"] else ""
                        print(f"  {b['id']}  ({b['name']})  model={b['model']}{active}")
            except httpx.HTTPError as e:
                print(f"  [action] Error listing bots: {e}")

        elif action == "show_history":
            try:
                data = client.get_session(ctx["session_id"])
                for msg in data["messages"]:
                    role = msg["role"].upper()
                    content = msg.get("content", "")
                    if role == "SYSTEM":
                        continue
                    print(f"  [{role}] {content}")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    print("  [action] No history yet for this session.")
                else:
                    print(f"  [action] Error: {e}")
            except httpx.HTTPError as e:
                print(f"  [action] Error: {e}")
