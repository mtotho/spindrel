"""Slash commands for the REPL (/new, /session, /bots, /v, etc.)."""
import sys
import uuid

import httpx

from agent_client.audio import (
    STT_AVAILABLE,
    WAKEWORD_AVAILABLE,
    check_tts_ready,
    listen_for_wakeword,
    play_tone,
    record_audio,
)
from agent_client.client import AgentClient
from agent_client.state import new_session_id, save_bot_id, save_session_id

from agent_client.cli.display import format_last_active
from agent_client.cli.voice import apply_bot_audio, transcribe


def _fuzzy_find_session(sessions, query):
    """Return a session dict matching query by uuid prefix or title, or None."""
    if not query:
        return None
    query = query.strip().lower()
    matches = [s for s in sessions if s["id"].lower().startswith(query)]
    if len(matches) == 1:
        return matches[0]
    matches_title = [s for s in sessions if s.get("title") and query in s["title"].lower()]
    if len(matches_title) == 1:
        return matches_title[0]
    if matches or matches_title:
        choices = matches + [m for m in matches_title if m not in matches]
        print("More than one session found matching your input:")
        for s in choices:
            title = s.get("title") or "(untitled)"
            print(f"  {s['id'][:8]} {title} bot={s['bot_id']}")
        print("  ⚄ Selecting first match...")
        return choices[0]
    return None


def handle_command(line: str, client: AgentClient, ctx: dict) -> bool:
    """Handle slash commands. Returns True if the input was a command."""
    parts = line.strip().split(maxsplit=1)
    cmd = parts[0].lower()

    if cmd in ("/quit", "/exit"):
        print("Goodbye.")
        sys.exit(0)

    elif cmd == "/new":
        ctx["session_id"] = new_session_id()
        print(f"New session: {ctx['session_id']}")
        return True

    elif cmd == "/delete":
        # Always list sessions and ask for a number to delete.
        try:
            sessions = client.list_sessions()
            if not sessions:
                print("No sessions to delete.")
                return True

            print("Current sessions:")
            for i, s in enumerate(sessions):
                title = (s.get("title") or "(untitled)")[:30]
                last = format_last_active(s.get("last_active", ""))
                print(f"  {i+1}. {s['id'][:8]}  {title}  bot={s['bot_id']}  client={s['client_id']} {last}")

            # If user gave a number, use it; else request one.
            delete_num = None
            if len(parts) >= 2 and parts[1].strip().isdigit():
                delete_num = int(parts[1].strip())
            else:
                user_in = input("Enter the number of the session to delete: ").strip()
                if not user_in.isdigit():
                    print("Invalid number.")
                    return True
                delete_num = int(user_in)

            index = delete_num - 1
            if index < 0 or index >= len(sessions):
                print("Invalid session number.")
                return True

            session_id = sessions[index]["id"]
            client.delete_session(uuid.UUID(session_id))
            print(f"Session {session_id[:8]} deleted.")

            # If we just deleted the current session: create and switch to a new one
            current_id_str = str(ctx["session_id"])
            if session_id == current_id_str or session_id == str(current_id_str):
                ctx["session_id"] = new_session_id()
                print(f"Deleted current session. Created new session: {ctx['session_id']}")
                save_session_id(ctx["session_id"])


        except Exception as e:
            print(f"Error deleting session: {e}")
        return True

    elif cmd == "/session":
        if len(parts) < 2:
            print(f"Current session: {ctx['session_id']}")
            return True
        try:
            sessions = client.list_sessions()
            raw = parts[1]
            if raw.isdigit():
                index = int(raw) - 1
                if index >= 0 and index < len(sessions):
                    ctx["session_id"] = sessions[index]["id"]
                    save_session_id(ctx["session_id"])
                    title = sessions[index].get("title") or "(untitled)"
                    print(f" ✓ Switched to session: {ctx['session_id'][:8]} {title}")
                else:
                    print("Invalid session number.")
                return True
            try:
                sid = uuid.UUID(raw)
                found = any(str(s["id"]) == str(sid) for s in sessions)
                if found:
                    ctx["session_id"] = sid
                    save_session_id(sid)
                    print(f"Switched to session: {sid}")
                else:
                    print("Session with this UUID not found.")
            except ValueError:
                found = _fuzzy_find_session(sessions, raw)
                if found:
                    ctx["session_id"] = uuid.UUID(found["id"])
                    save_session_id(ctx["session_id"])
                    print(f"Switched to session: {found['id']} ({found.get('title', '(untitled)')})")
                else:
                    print("No session found matching identifier or title.")
        except Exception as e:
            print(f"Error looking up session: {e}")
        return True

    elif cmd == "/sessions":
        try:
            sessions = client.list_sessions()
            if not sessions:
                print("No sessions.")
            else:
                for i, s in enumerate(sessions):
                    selected = str(ctx["session_id"]) == s["id"]
                    arrow = "[*]" if selected else ""
                    title = (s.get("title") or "(untitled)")[:30]
                    last = format_last_active(s.get("last_active", ""))
                   
                    if selected:
                        print(f"  {arrow} {i+1}. {s['id'][:8]}  {title}  bot={s['bot_id']}  client={s['client_id']} {last}")
                    else:
                        print(f"      {i+1}. {s['id'][:8]}  {title}  bot={s['bot_id']}  client={s['client_id']} {last}")
                print("  ")
                print("  Select a session by typing /session <partial id or title or number>")
        except httpx.HTTPError as e:
            print(f"Error listing sessions: {e}")
        return True

    elif cmd == "/history":
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
                print("No history yet for this session.")
            else:
                print(f"Error: {e}")
        except httpx.HTTPError as e:
            print(f"Error: {e}")
        return True

    elif cmd == "/bots":
        try:
            bots = client.list_bots()
            if not bots:
                print("No bots configured.")
            else:
                for b in bots:
                    active = " *" if ctx["bot_id"] == b["id"] else ""
                    print(f"  {b['id']}  ({b['name']})  model={b['model']}{active}")
        except httpx.HTTPError as e:
            print(f"Error listing bots: {e}")
        return True

    elif cmd == "/bot":
        if len(parts) < 2:
            print(f"Current bot: {ctx['bot_id']}")
        else:
            ctx["bot_id"] = parts[1]
            save_bot_id(parts[1])
            apply_bot_audio(client, ctx)
            audio_mode = "native" if ctx.get("audio_native") else "transcribe"
            print(f"Switched bot to: {ctx['bot_id']} | audio {audio_mode}")
        return True

    elif cmd in ("/v", "/voice"):
        if not STT_AVAILABLE:
            print("Voice input not available. Install with: pip install -e \"client/[voice]\"")
            return True
        audio = record_audio()
        if audio is None:
            return True
        if ctx.get("audio_native"):
            ctx["_voice_audio"] = audio
            return False
        text = transcribe(audio, client, ctx)
        if text is None:
            return True
        print(f"  You said: {text}")
        ctx["_voice_text"] = text
        return False

    elif cmd == "/vc":
        if not STT_AVAILABLE:
            print("Voice input not available. Install with: pip install -e \"client/[voice]\"")
            return True
        ctx["_voice_conversation"] = True
        print("Voice conversation mode. Speak after each response. Stay silent or Ctrl+C to exit.")
        audio = record_audio()
        if audio is None:
            ctx.pop("_voice_conversation", None)
            print("Voice conversation ended.")
            return True
        if ctx.get("audio_native"):
            ctx["_voice_audio"] = audio
            return False
        text = transcribe(audio, client, ctx)
        if text is None:
            ctx.pop("_voice_conversation", None)
            print("Voice conversation ended.")
            return True
        print(f"  You said: {text}")
        ctx["_voice_text"] = text
        return False

    elif cmd == "/listen":
        if not WAKEWORD_AVAILABLE:
            print("Wake word not available. Install with: pip install -e \"client/[wakeword]\"")
            return True
        if not STT_AVAILABLE:
            print("Voice input not available. Install with: pip install -e \"client/[voice]\"")
            return True
        ctx["_wake_word_mode"] = True
        detected = listen_for_wakeword(ctx["wake_words"])
        if detected is None:
            ctx.pop("_wake_word_mode", None)
            return True
        play_tone(preset=ctx.get("listen_sound", "chime"))
        audio = record_audio()
        if audio is None:
            ctx.pop("_wake_word_mode", None)
            return True
        if ctx.get("audio_native"):
            ctx["_voice_audio"] = audio
            return False
        text = transcribe(audio, client, ctx)
        if text is None:
            ctx.pop("_wake_word_mode", None)
            return True
        print(f"  You said: {text}")
        ctx["_voice_text"] = text
        return False

    elif cmd == "/tts":
        if ctx["tts"]:
            ctx["tts"] = False
            print("TTS off")
        else:
            err = check_tts_ready(ctx["piper_model"], ctx["piper_model_dir"])
            if err:
                print(f"Cannot enable TTS: {err}")
            else:
                ctx["tts"] = True
                print("TTS on")
        return True

    elif cmd == "/tts_voice":
        if len(parts) < 2:
            print(f"TTS voice: {ctx['piper_model']} (set in config or: /tts_voice <model>)")
        else:
            model = parts[1]
            err = check_tts_ready(model, ctx["piper_model_dir"])
            if err:
                print(f"Cannot use that voice: {err}")
            else:
                ctx["piper_model"] = model
                print(f"TTS voice set to: {model}")
        return True

    elif cmd == "/tone":
        presets = ("chime", "beep", "ping")
        if len(parts) < 2:
            print(f"Listen tone: {ctx.get('listen_sound', 'chime')} (options: {', '.join(presets)})")
        else:
            preset = parts[1].lower()
            if preset in presets:
                ctx["listen_sound"] = preset
                print(f"Listen tone set to: {preset}")
            else:
                print(f"Unknown preset. Use one of: {', '.join(presets)}")
        return True

    elif cmd == "/compact":
        try:
            print("  Compacting session...")
            result = client.summarize_session(ctx["session_id"])
            print(f"  Title: {result.get('title', '(none)')}")
            summary = result.get("summary", "")
            if len(summary) > 200:
                summary = summary[:200] + "..."
            print(f"  Summary: {summary}")
         
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                print("Session not found on server (send a message first).")
            elif e.response.status_code == 400:
                print("Nothing to summarize yet.")
            else:
                print(f"Error: {e}")
        except httpx.HTTPError as e:
            print(f"Error: {e}")
        return True

    elif cmd == "/audio":
        ctx["audio_native"] = not ctx.get("audio_native", False)
        state = "native" if ctx["audio_native"] else "transcribe"
        print(f"Audio input mode: {state}")
        return True

    elif cmd == "/help":
        print("Commands:")
        print("  /new             Start a new session")
        print("  /session [uuid]  Show or switch session")
        print("  /sessions        List all sessions")
        print("  /history         Show current session history")
        print("  /compact         Force compaction + memory storage now")
        print("  /v               Voice input (single turn)")
        print("  /vc              Voice conversation (continuous)")
        print("  /listen          Wake word mode (say wake word to talk)")
        print("  /bots            List available bots")
        print("  /bot [id]        Show or switch bot")
        print("  /tts             Toggle text-to-speech")
        print("  /tts_voice [model] GET or SET TTS voice")
        print("  /tone [preset]   GET or SET listen tone")
        print("  /audio           Toggle native audio (send audio to model directly)")
        print("  /quit            Exit")
        return True

    return False
