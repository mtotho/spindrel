import argparse
import sys
import uuid

import httpx

from agent_client.audio import (
    STT_AVAILABLE, TTS_AVAILABLE,
    check_stt_ready, check_tts_ready,
    record_audio, speak, transcribe,
)
from agent_client.client import AgentClient
from agent_client.config import load_config
from agent_client.state import load_bot_id, load_session_id, new_session_id, save_bot_id, save_session_id


def _short_id(sid: uuid.UUID) -> str:
    return str(sid)[:6]


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
            sid = uuid.UUID(parts[1])
            ctx["session_id"] = sid
            save_session_id(sid)
            print(f"Switched to session: {sid}")
        except ValueError:
            print("Invalid UUID.")
        return True

    elif cmd == "/sessions":
        try:
            sessions = client.list_sessions()
            if not sessions:
                print("No sessions.")
            else:
                for s in sessions:
                    active = " *" if str(ctx["session_id"]) == s["id"] else ""
                    print(f"  {s['id'][:8]}  bot={s['bot_id']}  client={s['client_id']}  last={s['last_active']}{active}")
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
            print(f"Switched bot to: {ctx['bot_id']}")
        return True

    elif cmd in ("/v", "/voice"):
        if not STT_AVAILABLE:
            print("Voice input not available. Install with: pip install -e \"client/[voice]\"")
            return True
        audio = record_audio()
        if audio is None:
            return True
        text = transcribe(audio, ctx["whisper_model"])
        if text is None:
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

    elif cmd == "/help":
        print("Commands:")
        print("  /new             Start a new session")
        print("  /session [uuid]  Show or switch session")
        print("  /sessions        List all sessions")
        print("  /history         Show current session history")
        print("  /v               Voice input (record + transcribe)")
        print("  /bots            List available bots")
        print("  /bot [id]        Show or switch bot")
        print("  /tts             Toggle text-to-speech")
        print("  /quit            Exit")
        return True

    return False


def main():
    parser = argparse.ArgumentParser(description="Agent Chat CLI")
    parser.add_argument("--bot", help="Bot ID to use")
    parser.add_argument("--url", help="Server URL override")
    parser.add_argument("--key", help="API key override")
    parser.add_argument("--tts", action="store_true", default=None, help="Enable TTS")
    parser.add_argument("--no-tts", dest="tts", action="store_false", help="Disable TTS")
    parser.add_argument("--voice", action="store_true", help="Enable voice input (install deps)")
    args = parser.parse_args()

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
        "whisper_model": config.whisper_model,
    }

    # Verify connectivity
    try:
        client.health()
    except httpx.HTTPError:
        print(f"Warning: Cannot reach server at {config.agent_url}")

    tts_status = "on" if ctx["tts"] else "off"
    print(f"Agent Chat — session {_short_id(ctx['session_id'])} | bot {ctx['bot_id']} | tts {tts_status}")
    print("Type /help for commands.\n")

    try:
        while True:
            try:
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
                if "_voice_text" in ctx:
                    line = ctx.pop("_voice_text")
                else:
                    continue

            try:
                result = client.chat(
                    message=line,
                    session_id=ctx["session_id"],
                    bot_id=ctx["bot_id"],
                )
                response_text = result["response"]
                print(f"\n{response_text}\n")
                if ctx["tts"] and response_text:
                    speak(response_text, ctx["piper_model"], ctx["piper_model_dir"])
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    print("Authentication failed. Check your API key.")
                elif e.response.status_code == 404:
                    print(f"Bot '{ctx['bot_id']}' not found.")
                else:
                    print(f"Server error ({e.response.status_code}): {e.response.text}")
            except httpx.ConnectError:
                print(f"Cannot connect to server at {config.agent_url}")
            except httpx.TimeoutException:
                print("Request timed out. The server may be processing a complex request.")
            except httpx.HTTPError as e:
                print(f"HTTP error: {e}")

    except KeyboardInterrupt:
        print("\nGoodbye.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
