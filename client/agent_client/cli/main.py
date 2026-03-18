"""CLI entry point and REPL loop."""
import argparse
import sys

import httpx

from agent_client.audio import (
    check_stt_ready,
    check_tts_ready,
    close_mic,
    listen_for_wakeword,
    play_tone,
    record_audio,
    speak,
)
from agent_client.client import AgentClient
from agent_client.config import load_config
from agent_client.state import load_bot_id, load_session_id

from agent_client.cli.actions import handle_client_actions
from agent_client.cli.commands import handle_command
from agent_client.cli.display import short_id, strip_silent
from agent_client.cli.streaming import send_streaming
from agent_client.cli.voice import (
    apply_bot_audio,
    audio_to_base64,
    speak_interruptible,
    transcribe,
)


def main() -> None:
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

    try:
        client.health()
        apply_bot_audio(client, ctx)
    except httpx.HTTPError:
        print(f"Warning: Cannot reach server at {config.agent_url}")

    tts_status = "on" if ctx["tts"] else "off"
    audio_mode = "native" if ctx.get("audio_native") else "transcribe"
    print(f"Agent Chat — session {short_id(ctx['session_id'])} | bot {ctx['bot_id']} | tts {tts_status} | audio {audio_mode}")
    print("Type /help for commands.\n")

    pending_input = "/listen" if args.listen else None

    try:
        while True:
            try:
                if pending_input is not None:
                    line = pending_input
                    pending_input = None
                else:
                    prompt = f"[{ctx['bot_id']}|{short_id(ctx['session_id'])}] > "
                    line = input(prompt)
            except EOFError:
                print("\nGoodbye.")
                break

            line = line.strip()
            if not line:
                continue

            if line.startswith("/"):
                if handle_command(line, client, ctx):
                    continue
                if "_voice_audio" in ctx:
                    voice_audio = ctx.pop("_voice_audio")
                    b64 = audio_to_base64(voice_audio)
                    try:
                        result = send_streaming(
                            client, "", ctx,
                            audio_data=b64, audio_format="wav", audio_native=True,
                        )
                        response_text = result["response"]
                        display_text, speakable_text, _ = strip_silent(response_text)
                        print(f"\n{display_text}\n")
                        handle_client_actions(result.get("client_actions", []), client, ctx)
                        if ctx["tts"] and speakable_text:
                            if ctx.get("_wake_word_mode"):
                                if speak_interruptible(speakable_text, ctx):
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
                        b64 = audio_to_base64(audio)
                        result = send_streaming(
                            client, "", ctx,
                            audio_data=b64, audio_format="wav", audio_native=True,
                        )
                        response_text = result["response"]
                        display_text, speakable_text, _ = strip_silent(response_text)
                        print(f"\n{display_text}\n")
                        handle_client_actions(result.get("client_actions", []), client, ctx)
                        if ctx["tts"] and speakable_text:
                            if ctx.get("_wake_word_mode"):
                                if speak_interruptible(speakable_text, ctx):
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
                result = send_streaming(client, line, ctx)
                response_text = result["response"]
                display_text, speakable_text, _ = strip_silent(response_text)
                print(f"\n{display_text}\n")
                handle_client_actions(result.get("client_actions", []), client, ctx)
                if ctx["tts"] and speakable_text:
                    if ctx.get("_wake_word_mode"):
                        if speak_interruptible(speakable_text, ctx):
                            play_tone(preset=ctx.get("listen_sound", "chime"))
                            ctx["_wakeword_predetected"] = True
                    else:
                        speak(speakable_text, ctx["piper_model"], ctx["piper_model_dir"], ctx.get("tts_speed", 1.0))

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
                    text = transcribe(audio, client, ctx)
                    if text is None:
                        if ctx.get("_wake_word_mode"):
                            continue
                        print("Voice conversation ended.")
                        ctx.pop("_voice_conversation", None)
                        break
                    print(f"  You said: {text}")
                    result = send_streaming(client, text, ctx)
                    response_text = result["response"]
                    display_text, speakable_text, _ = strip_silent(response_text)
                    print(f"\n{display_text}\n")
                    handle_client_actions(result.get("client_actions", []), client, ctx)
                    if ctx["tts"] and speakable_text:
                        if ctx.get("_wake_word_mode"):
                            if speak_interruptible(speakable_text, ctx):
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
