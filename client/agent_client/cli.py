import argparse
import json
import re
import subprocess
import sys
import threading
import uuid

import httpx

from agent_client.audio import (
    STT_AVAILABLE, TTS_AVAILABLE, WAKEWORD_AVAILABLE,
    check_stt_ready, check_tts_ready, check_wakeword_ready,
    close_mic, listen_for_wakeword, play_tone, record_audio, speak, stop_speaking,
    transcribe as local_transcribe,
)
from agent_client.client import AgentClient
from agent_client.config import load_config
from agent_client.state import load_bot_id, load_session_id, new_session_id, save_bot_id, save_session_id


_TOOL_DISPLAY_NAMES = {
    "web_search": "Searching the web",
    "fetch_url": "Reading webpage",
    "get_current_time": "Checking the time",
    "search_memories": "Searching memories",
    "save_memory": "Saving to memory",
    "client_action": None,
    "shell_exec": None,  # handled specially via tool_request
}


_SILENT_RE = re.compile(r"\[silent\](.*?)\[/silent\]", re.DOTALL)


def _strip_silent(text: str) -> tuple[str, str, bool]:
    """Parse [silent]...[/silent] markers from response text.

    Returns (display_text, speakable_text, has_silent).
    - display_text: full text with markers stripped (shown in terminal)
    - speakable_text: only the non-silent portions (sent to TTS)
    - has_silent: whether any silent markers were found
    """
    if "[silent]" not in text:
        return text, text, False

    speakable = _SILENT_RE.sub("", text).strip()
    display = _SILENT_RE.sub(lambda m: f"\033[2m{m.group(1)}\033[0m", text)
    return display, speakable, True


def _execute_client_tool(tool_name: str, arguments: dict) -> str:
    """Execute a client-side tool and return the result as a string."""
    if tool_name == "shell_exec":
        command = arguments.get("command", "")
        print(f"  [shell] $ {command}")
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = proc.stdout
            if proc.stderr:
                output += ("\n" if output else "") + proc.stderr
            if proc.returncode != 0:
                output += f"\n[exit code {proc.returncode}]"
            return output.strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return "[error: command timed out after 30s]"
        except Exception as e:
            return f"[error: {e}]"

    return json.dumps({"error": f"Unknown client tool: {tool_name}"})


def _tool_status(tool_name: str) -> str | None:
    """Return a human-readable status string, or None to suppress display."""
    if tool_name in _TOOL_DISPLAY_NAMES:
        return _TOOL_DISPLAY_NAMES[tool_name]
    return f"Using {tool_name}"


def _speak_interruptible(response_text: str, ctx: dict) -> bool:
    """Speak response in a background thread while listening for wake word.

    Returns True if the wake word interrupted TTS playback.
    """
    tts_done = threading.Event()

    def _tts_worker():
        speak(response_text, ctx["piper_model"], ctx["piper_model_dir"], ctx.get("tts_speed", 1.0))
        tts_done.set()

    thread = threading.Thread(target=_tts_worker, daemon=True)
    thread.start()

    detected = listen_for_wakeword(ctx["wake_words"], stop_event=tts_done)
    stop_speaking()
    thread.join(timeout=2)
    return detected is not None


def _send_streaming(
    client: AgentClient,
    message: str,
    ctx: dict,
    audio_data: str | None = None,
    audio_format: str | None = None,
    audio_native: bool | None = None,
) -> dict:
    """Send a message via streaming and display tool status in real time.

    Handles tool_request events by executing client-side tools and posting
    results back to the server, then continues reading the stream.

    Returns a dict with 'response', 'transcript', and 'client_actions'.
    """
    response_text = ""
    transcript_text = ""
    client_actions: list[dict] = []

    for event in client.chat_stream(
        message=message,
        session_id=ctx["session_id"],
        bot_id=ctx["bot_id"],
        audio_data=audio_data,
        audio_format=audio_format,
        audio_native=audio_native,
    ):
        etype = event.get("type")

        if etype == "skill_context":
            count = event.get("count", 0)
            print(f"  [Using {count} skill chunk{'s' if count != 1 else ''}...]")

        elif etype == "memory_context":
            count = event.get("count", 0)
            print(f"  [Recalled {count} memor{'ies' if count != 1 else 'y'}...]")

        elif etype == "tool_start":
            label = _tool_status(event.get("tool", ""))
            if label:
                print(f"  [{label}...]")

        elif etype == "tool_request":
            tool_name = event.get("tool", "")
            arguments = event.get("arguments", {})
            request_id = event.get("request_id", "")
            result = _execute_client_tool(tool_name, arguments)
            try:
                client.submit_tool_result(request_id, result)
            except httpx.HTTPError as e:
                print(f"  [error submitting tool result: {e}]")

        elif etype == "tool_result":
            if "error" in event:
                print(f"  [error: {event['error']}]")
            else:
                tool_name = event.get("tool", "")
                if tool_name == "search_memories":
                    count = event.get("memory_count")
                    if count is not None:
                        if count == 0:
                            print(f"  [No memories found]")
                        else:
                            print(f"  [Found {count} memor{'y' if count == 1 else 'ies'}]")
                            preview = event.get("memory_preview")
                            if preview:
                                print(f"    \033[2m{preview}\033[0m")
                elif tool_name == "save_memory" and event.get("saved"):
                    print(f"  [Saved to memory]")

        elif etype == "transcript":
            transcript_text = event.get("text", "")
            print(f"  [heard: {transcript_text}]")

        elif etype == "response":
            response_text = event.get("text", "")
            client_actions = event.get("client_actions", [])

        elif etype == "error":
            detail = event.get("detail", "Unknown error")
            print(f"  [error] {detail}")

    return {"response": response_text, "transcript": transcript_text, "client_actions": client_actions}


def _short_id(sid: uuid.UUID) -> str:
    return str(sid)[:6]


def _format_last_active(raw: str) -> str:
    """Turn an ISO timestamp into a human-friendly relative time."""
    if not raw:
        return ""
    try:
        from datetime import datetime, timezone
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
        return raw[:16]


def _handle_client_actions(actions: list[dict], client: AgentClient, ctx: dict) -> None:
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
                _apply_bot_audio(client, ctx)
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
                        last = _format_last_active(s.get("last_active", ""))
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


def _fuzzy_find_session(sessions, query):
    """Return a session dict matching query by uuid prefix or title (case-insensitive substring), or None."""
    if not query:
        return None
    query = query.strip().lower()
    # 1. Try prefix match on UUID
    matches = [s for s in sessions if s["id"].lower().startswith(query)]
    if len(matches) == 1:
        return matches[0]
    # 2. Try substring in title
    matches_title = [s for s in sessions if s.get("title") and query in s["title"].lower()]
    if len(matches_title) == 1:
        return matches_title[0]
    # 3. Return None or, if several matches, print them for user hint
    if matches or matches_title:
        choices = matches + [m for m in matches_title if m not in matches]
        print("More than one session found matching your input:")
        for s in choices:
            title = s.get("title") or "(untitled)"
            print(f"  {s['id'][:8]} {title} bot={s['bot_id']}")

        print("  ⚄ Selecting first match...")
        return choices[0]
    return None


def _handle_command(line: str, client: AgentClient, ctx: dict) -> bool:
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
            # Try exact UUID
            try:
                sid = uuid.UUID(raw)
                # Verify this UUID exists in list
                found = any(str(s["id"]) == str(sid) for s in sessions)
                if found:
                    ctx["session_id"] = sid
                    save_session_id(sid)
                    print(f"Switched to session: {sid}")
                else:
                    print("Session with this UUID not found.")
            except ValueError:
                # Fuzzy match by id prefix or title
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
                index = 0
                for i, s in enumerate(sessions):
                    selected = str(ctx["session_id"]) == s["id"]
                    arrow = "[*]" if selected else ""
                    title = (s.get("title") or "(untitled)")[:30]
                    last = _format_last_active(s.get("last_active", ""))
                    if selected:
                        print(f"  {arrow} {i+1}. {s['id'][:8]}  {title}  bot={s['bot_id']}  {last}")
                    else:
                        print(f"      {i+1}. {s['id'][:8]}  {title}  bot={s['bot_id']}  {last}")

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
            _apply_bot_audio(client, ctx)
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
        text = _transcribe(audio, client, ctx)
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
        text = _transcribe(audio, client, ctx)
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
        text = _transcribe(audio, client, ctx)
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
            if result.get("memory_written"):
                print("  Memory written to KB.")
            else:
                print("  No memory written (disabled or filtered out).")
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


def _transcribe(audio, client: AgentClient, ctx: dict) -> str | None:
    """Transcribe audio, trying server-side first then falling back to local."""
    import numpy as np

    try:
        audio_bytes = audio.flatten().astype(np.float32).tobytes()
        text = client.transcribe(audio_bytes)
        if text is not None:
            return text
    except Exception:
        pass

    return local_transcribe(audio, ctx["whisper_model"])


def _audio_to_base64(audio) -> str:
    """Convert a numpy audio array to base64-encoded WAV for native audio input."""
    import base64
    import io
    import struct

    import numpy as np

    samples = audio.flatten().astype(np.float32)
    # Encode as 16-bit PCM WAV
    pcm = (samples * 32767).astype(np.int16)
    buf = io.BytesIO()
    num_samples = len(pcm)
    data_size = num_samples * 2
    # WAV header
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16))
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(pcm.tobytes())
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _apply_bot_audio(client: AgentClient, ctx: dict) -> None:
    """Fetch audio config for current bot from server (e.g. audio_input=native). Voice/tone stay client-local."""
    try:
        bots = client.list_bots()
        for b in bots:
            if b["id"] == ctx["bot_id"]:
                ctx["audio_native"] = b.get("audio_input") == "native" or ctx["_default_audio_native"]
                return
    except Exception:
        pass
    ctx["audio_native"] = ctx["_default_audio_native"]


def main():
    parser = argparse.ArgumentParser(description="Agent Chat CLI")
    parser.add_argument("--bot", help="Bot ID to use")
    parser.add_argument("--url", help="Server URL override")
    parser.add_argument("--key", help="API key override")
    parser.add_argument("--tts", action="store_true", default=None, help="Enable TTS")
    parser.add_argument("--no-tts", dest="tts", action="store_false", help="Disable TTS")
    parser.add_argument("--voice", action="store_true", help="Enable voice input (install deps)")
    parser.add_argument("--listen", action="store_true", help="Start in wake word listen mode")
    args = parser.parse_args()

    if args.listen:
        args.voice = True

    config = load_config()
    saved_bot = load_bot_id()
    if args.bot:
        config.bot_id = args.bot
    elif saved_bot:
        config.bot_id = saved_bot
    if args.url:
        config.agent_url = args.url.rstrip("/")
    if args.key:
        config.api_key = args.key

    if args.tts is not None:
        config.tts_enabled = args.tts

    if not config.api_key:
        print("Error: API_KEY not set. Set it in ~/.config/agent-client/config.env or pass --key.")
        sys.exit(1)

    tts_on = False
    if config.tts_enabled:
        print("Checking TTS...")
        tts_err = check_tts_ready(config.piper_model, config.piper_model_dir)
        if tts_err:
            print(f"Error: {tts_err}")
            sys.exit(1)
        tts_on = True
        print("TTS ready.")

    if args.voice:
        print("Checking voice input...")
        stt_err = check_stt_ready()
        if stt_err:
            print(f"Error: {stt_err}")
            sys.exit(1)
        import sounddevice as sd
        default_input = sd.query_devices(kind="input")
        print(f"Voice ready. Mic: {default_input['name']}")  # type: ignore[index]

    client = AgentClient(config.agent_url, config.api_key)
    session_id = load_session_id()

    ctx = {
        "session_id": session_id,
        "bot_id": config.bot_id,
        "tts": tts_on,
        "piper_model": config.piper_model,
        "piper_model_dir": config.piper_model_dir,
        "tts_speed": config.tts_speed,
        "listen_sound": config.listen_sound,
        "whisper_model": config.whisper_model,
        "wake_words": config.wake_words,
        "audio_native": config.audio_native,
        "_default_piper_model": config.piper_model,
        "_default_tts_speed": config.tts_speed,
        "_default_listen_sound": config.listen_sound,
        "_default_audio_native": config.audio_native,
    }

    # Verify connectivity and load bot voice config
    try:
        client.health()
        _apply_bot_audio(client, ctx)
    except httpx.HTTPError:
        print(f"Warning: Cannot reach server at {config.agent_url}")

    tts_status = "on" if ctx["tts"] else "off"
    audio_mode = "native" if ctx.get("audio_native") else "transcribe"
    print(f"Agent Chat — session {_short_id(ctx['session_id'])} | bot {ctx['bot_id']} | tts {tts_status} | audio {audio_mode}")
    print("Type /help for commands.\n")

    pending_input = "/listen" if args.listen else None

    try:
        while True:
            try:
                if pending_input is not None:
                    line = pending_input
                    pending_input = None
                else:
                    prompt = f"[{ctx['bot_id']}|{_short_id(ctx['session_id'])}] > "
                    line = input(prompt)
            except EOFError:
                print("\nGoodbye.")
                break

            line = line.strip()
            if not line:
                continue

            if line.startswith("/"):
                if _handle_command(line, client, ctx):
                    continue
                if "_voice_audio" in ctx:
                    voice_audio = ctx.pop("_voice_audio")
                    b64 = _audio_to_base64(voice_audio)
                    try:
                        result = _send_streaming(
                            client, "", ctx,
                            audio_data=b64, audio_format="wav", audio_native=True,
                        )
                        response_text = result["response"]
                        display_text, speakable_text, _ = _strip_silent(response_text)
                        print(f"\n{display_text}\n")
                        _handle_client_actions(result.get("client_actions", []), client, ctx)
                        if ctx["tts"] and speakable_text:
                            if ctx.get("_wake_word_mode"):
                                if _speak_interruptible(speakable_text, ctx):
                                    play_tone(preset=ctx.get("listen_sound", "chime"))
                                    ctx["_wakeword_predetected"] = True
                            else:
                                speak(speakable_text, ctx["piper_model"], ctx["piper_model_dir"], ctx.get("tts_speed", 1.0))
                    except KeyboardInterrupt:
                        if ctx.get("_voice_conversation") or ctx.get("_wake_word_mode"):
                            print("\nVoice mode ended.")
                            ctx.pop("_voice_conversation", None)
                            ctx.pop("_wake_word_mode", None)
                        else:
                            raise
                    except httpx.HTTPError as e:
                        ctx.pop("_voice_conversation", None)
                        print(f"HTTP error: {e}")

                    # Voice conversation loop for native audio
                    while ctx.get("_voice_conversation") or ctx.get("_wake_word_mode"):
                        if ctx.get("_wake_word_mode") and not ctx.pop("_wakeword_predetected", False):
                            detected = listen_for_wakeword(ctx["wake_words"])
                            if detected is None:
                                ctx.pop("_wake_word_mode", None)
                                break
                            play_tone(preset=ctx.get("listen_sound", "chime"))

                        audio = record_audio()
                        if audio is None:
                            if ctx.get("_wake_word_mode"):
                                continue
                            print("Voice conversation ended.")
                            ctx.pop("_voice_conversation", None)
                            break
                        b64 = _audio_to_base64(audio)
                        result = _send_streaming(
                            client, "", ctx,
                            audio_data=b64, audio_format="wav", audio_native=True,
                        )
                        response_text = result["response"]
                        display_text, speakable_text, _ = _strip_silent(response_text)
                        print(f"\n{display_text}\n")
                        _handle_client_actions(result.get("client_actions", []), client, ctx)
                        if ctx["tts"] and speakable_text:
                            if ctx.get("_wake_word_mode"):
                                if _speak_interruptible(speakable_text, ctx):
                                    play_tone(preset=ctx.get("listen_sound", "chime"))
                                    ctx["_wakeword_predetected"] = True
                            else:
                                speak(speakable_text, ctx["piper_model"], ctx["piper_model_dir"], ctx.get("tts_speed", 1.0))
                    continue
                elif "_voice_text" in ctx:
                    line = ctx.pop("_voice_text")
                else:
                    continue

            try:
                result = _send_streaming(client, line, ctx)
                response_text = result["response"]
                display_text, speakable_text, _ = _strip_silent(response_text)
                print(f"\n{display_text}\n")
                _handle_client_actions(result.get("client_actions", []), client, ctx)
                if ctx["tts"] and speakable_text:
                    if ctx.get("_wake_word_mode"):
                        if _speak_interruptible(speakable_text, ctx):
                            play_tone(preset=ctx.get("listen_sound", "chime"))
                            ctx["_wakeword_predetected"] = True
                    else:
                        speak(speakable_text, ctx["piper_model"], ctx["piper_model_dir"], ctx.get("tts_speed", 1.0))

                # Voice conversation loop: auto-listen after response
                while ctx.get("_voice_conversation") or ctx.get("_wake_word_mode"):
                    if ctx.get("_wake_word_mode") and not ctx.pop("_wakeword_predetected", False):
                        detected = listen_for_wakeword(ctx["wake_words"])
                        if detected is None:
                            ctx.pop("_wake_word_mode", None)
                            break
                        play_tone(preset=ctx.get("listen_sound", "chime"))

                    audio = record_audio()
                    if audio is None:
                        if ctx.get("_wake_word_mode"):
                            continue  # No speech, go back to listening for wake word
                        print("Voice conversation ended.")
                        ctx.pop("_voice_conversation", None)
                        break
                    text = _transcribe(audio, client, ctx)
                    if text is None:
                        if ctx.get("_wake_word_mode"):
                            continue
                        print("Voice conversation ended.")
                        ctx.pop("_voice_conversation", None)
                        break
                    print(f"  You said: {text}")
                    result = _send_streaming(client, text, ctx)
                    response_text = result["response"]
                    display_text, speakable_text, _ = _strip_silent(response_text)
                    print(f"\n{display_text}\n")
                    _handle_client_actions(result.get("client_actions", []), client, ctx)
                    if ctx["tts"] and speakable_text:
                        if ctx.get("_wake_word_mode"):
                            if _speak_interruptible(speakable_text, ctx):
                                play_tone(preset=ctx.get("listen_sound", "chime"))
                                ctx["_wakeword_predetected"] = True
                        else:
                            speak(speakable_text, ctx["piper_model"], ctx["piper_model_dir"], ctx.get("tts_speed", 1.0))

            except KeyboardInterrupt:
                if ctx.get("_voice_conversation") or ctx.get("_wake_word_mode"):
                    print("\nVoice mode ended.")
                    ctx.pop("_voice_conversation", None)
                    ctx.pop("_wake_word_mode", None)
                else:
                    raise
            except httpx.HTTPStatusError as e:
                ctx.pop("_voice_conversation", None)
                if e.response.status_code == 401:
                    print("Authentication failed. Check your API key.")
                elif e.response.status_code == 404:
                    print(f"Bot '{ctx['bot_id']}' not found.")
                else:
                    print(f"Server error ({e.response.status_code}): {e.response.text}")
            except httpx.ConnectError:
                ctx.pop("_voice_conversation", None)
                print(f"Cannot connect to server at {config.agent_url}")
            except httpx.TimeoutException:
                ctx.pop("_voice_conversation", None)
                print("Request timed out. The server may be processing a complex request.")
            except httpx.HTTPError as e:
                ctx.pop("_voice_conversation", None)
                print(f"HTTP error: {e}")

    except KeyboardInterrupt:
        print("\nGoodbye.")
    finally:
        close_mic()
        client.close()


if __name__ == "__main__":
    main()
