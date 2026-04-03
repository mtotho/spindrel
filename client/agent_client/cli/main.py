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
from agent_client.state import (
    load_bot_id,
    load_channel_id,
    load_model_override,
    load_session_id,
)

from agent_client.cli.actions import handle_client_actions
from agent_client.cli.commands import handle_command
from agent_client.cli.display import (
    console,
    make_prompt,
    print_banner,
    print_error,
    print_warning,
    short_id,
    strip_silent,
)
from agent_client.cli.streaming import send_streaming
from agent_client.cli.voice import (
    apply_bot_audio,
    audio_to_base64,
    speak_interruptible,
    transcribe,
)


def _run_tool_subcommand(args, config):
    """Handle `agent tool list|exec|schema` subcommands."""
    client = AgentClient(config.agent_url, config.api_key)
    try:
        if args.tool_action == "list":
            tools = client.list_tools()
            if args.json_output:
                import json
                print(json.dumps(tools, indent=2))
            else:
                from rich.table import Table
                table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
                table.add_column("Tool", max_width=35)
                table.add_column("Source", style="dim")
                table.add_column("Description", max_width=60, style="dim")
                for t in tools:
                    src = t.get("server_name") or t.get("source_integration") or "local"
                    desc = (t.get("description") or "")[:60]
                    table.add_row(t["tool_name"], src, desc)
                console.print(table)
                console.print(f"  [dim]{len(tools)} tools total[/dim]")

        elif args.tool_action == "exec":
            import json as _json
            tool_args = {}
            if args.tool_args:
                for pair in args.tool_args:
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        try:
                            v = _json.loads(v)
                        except (_json.JSONDecodeError, ValueError):
                            pass
                        tool_args[k] = v
                    else:
                        try:
                            tool_args = _json.loads(pair)
                        except _json.JSONDecodeError:
                            print_error(f"Cannot parse argument '{pair}'. Use key=value or JSON.")
                            sys.exit(1)
            result = client.execute_tool(args.tool_name, tool_args)
            if result.get("error"):
                print(_json.dumps(result["result"], indent=2), file=sys.stderr)
                sys.exit(1)
            else:
                out = result["result"]
                print(_json.dumps(out, indent=2) if isinstance(out, (dict, list)) else str(out))

        elif args.tool_action == "schema":
            import json as _json
            tools = client.list_tools()
            match = next((t for t in tools if t["tool_name"] == args.tool_name), None)
            if not match:
                print_error(f"Tool '{args.tool_name}' not found.")
                sys.exit(1)
            from rich.syntax import Syntax
            schema = match.get("schema_") or match.get("parameters", {})
            console.print(Syntax(_json.dumps(schema, indent=2), "json"))

        else:
            print_error(f"Unknown tool action: {args.tool_action}")
            sys.exit(1)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            print_error(f"Tool '{getattr(args, 'tool_name', '?')}' not found.")
        else:
            print_error(f"Error: {e.response.status_code} — {e.response.text[:200]}")
        sys.exit(1)
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent Chat CLI")
    parser.add_argument("--bot", help="Bot ID to use")
    parser.add_argument("--url", help="Server URL override")
    parser.add_argument("--key", help="API key override")
    parser.add_argument("--tts", action="store_true", default=None, help="Enable TTS")
    parser.add_argument("--no-tts", dest="tts", action="store_false", help="Disable TTS")
    parser.add_argument("--voice", action="store_true", help="Enable voice input (install deps)")
    parser.add_argument("--listen", action="store_true", help="Start in wake word listen mode")
    parser.add_argument("--channel", help="Channel ID to use")

    sub = parser.add_subparsers(dest="subcommand")

    tool_parser = sub.add_parser("tool", help="Direct tool execution")
    tool_sub = tool_parser.add_subparsers(dest="tool_action")

    list_p = tool_sub.add_parser("list", help="List all available tools")
    list_p.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")

    exec_p = tool_sub.add_parser("exec", help="Execute a tool")
    exec_p.add_argument("tool_name", help="Tool name (e.g. sonarr_queue)")
    exec_p.add_argument("tool_args", nargs="*", help="Arguments as key=value pairs or JSON object")

    schema_p = tool_sub.add_parser("schema", help="Show tool schema")
    schema_p.add_argument("tool_name", help="Tool name")

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
        print_error("API_KEY not set. Set it in ~/.config/agent-client/config.env or pass --key.")
        sys.exit(1)

    # Handle non-interactive subcommands
    if args.subcommand == "tool":
        if not args.tool_action:
            parser.parse_args(["tool", "--help"])
        _run_tool_subcommand(args, config)
        return

    tts_on = False
    if config.tts_enabled:
        console.print("[dim]Checking TTS...[/dim]")
        tts_err = check_tts_ready(config.piper_model, config.piper_model_dir)
        if tts_err:
            print_error(tts_err)
            sys.exit(1)
        tts_on = True
        console.print("[dim]TTS ready.[/dim]")

    if args.voice:
        console.print("[dim]Checking voice input...[/dim]")
        stt_err = check_stt_ready()
        if stt_err:
            print_error(stt_err)
            sys.exit(1)
        import sounddevice as sd
        default_input = sd.query_devices(kind="input")
        console.print(f"[dim]Voice ready. Mic: {default_input['name']}[/dim]")  # type: ignore[index]

    client = AgentClient(config.agent_url, config.api_key)
    session_id = load_session_id()
    channel_id = args.channel or load_channel_id()
    model_override, model_provider_id_override = load_model_override()

    ctx = {
        "session_id": session_id,
        "bot_id": config.bot_id,
        "client_id": "cli",
        "channel_id": channel_id,
        "model_override": model_override,
        "model_provider_id_override": model_provider_id_override,
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
        print_warning(f"Cannot reach server at {config.agent_url}")

    print_banner(
        ctx["bot_id"],
        str(ctx["session_id"]),
        ctx.get("channel_id"),
        ctx["tts"],
    )

    pending_input = "/listen" if args.listen else None

    try:
        while True:
            try:
                if pending_input is not None:
                    line = pending_input
                    pending_input = None
                else:
                    prompt = make_prompt(ctx["bot_id"], ctx.get("channel_id"), ctx.get("model_override"))
                    line = input(prompt)
            except EOFError:
                console.print("\n[dim]Goodbye.[/dim]")
                break

            line = line.strip()
            if not line:
                continue

            if line.startswith("/"):
                if handle_command(line, client, ctx):
                    # Clear attachments after command (they're not sent)
                    continue
                if "_voice_audio" in ctx:
                    voice_audio = ctx.pop("_voice_audio")
                    b64 = audio_to_base64(voice_audio)
                    try:
                        result = send_streaming(
                            client, "", ctx,
                            audio_data=b64, audio_format="wav", audio_native=True,
                        )
                        _handle_response(result, client, ctx)
                        if not result.get("cancelled"):
                            _voice_loop(client, ctx, native=True)
                    except KeyboardInterrupt:
                        _exit_voice(ctx)
                    except httpx.HTTPError as e:
                        ctx.pop("_voice_conversation", None)
                        print_error(f"HTTP error: {e}")
                    continue
                elif "_voice_text" in ctx:
                    line = ctx.pop("_voice_text")
                else:
                    continue

            # Send message
            try:
                result = send_streaming(client, line, ctx)
                _handle_response(result, client, ctx)
                # Clear attachments after send
                ctx.pop("_attachments", None)
                if not result.get("cancelled"):
                    _voice_loop(client, ctx, native=False)

            except KeyboardInterrupt:
                _exit_voice(ctx)
            except httpx.HTTPStatusError as e:
                ctx.pop("_voice_conversation", None)
                if e.response.status_code == 401:
                    print_error("Authentication failed. Check your API key.")
                elif e.response.status_code == 404:
                    print_error(f"Bot '{ctx['bot_id']}' not found.")
                else:
                    print_error(f"Server error ({e.response.status_code}): {e.response.text}")
            except httpx.ConnectError:
                ctx.pop("_voice_conversation", None)
                print_error(f"Cannot connect to server at {config.agent_url}")
            except httpx.TimeoutException:
                ctx.pop("_voice_conversation", None)
                print_error("Request timed out. The server may be processing a complex request.")
            except httpx.HTTPError as e:
                ctx.pop("_voice_conversation", None)
                print_error(f"HTTP error: {e}")

    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye.[/dim]")
    finally:
        close_mic()
        client.close()


def _handle_response(result: dict, client: AgentClient, ctx: dict) -> None:
    """Process a streaming result: client actions + TTS.

    Note: markdown display is already handled by StreamDisplay.finish() in streaming.py.
    """
    # Always process client actions, even if response text is empty
    handle_client_actions(result.get("client_actions", []), client, ctx)

    response_text = result.get("response", "")
    if not response_text:
        return
    _display_text, speakable_text, _ = strip_silent(response_text)
    if ctx["tts"] and speakable_text:
        if ctx.get("_wake_word_mode"):
            if speak_interruptible(speakable_text, ctx):
                play_tone(preset=ctx.get("listen_sound", "chime"))
                ctx["_wakeword_predetected"] = True
        else:
            speak(speakable_text, ctx["piper_model"], ctx["piper_model_dir"], ctx.get("tts_speed", 1.0))


def _voice_loop(client: AgentClient, ctx: dict, native: bool) -> None:
    """Continue voice conversation / wake word loop if active."""
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
            console.print("  [dim]Voice conversation ended.[/dim]")
            ctx.pop("_voice_conversation", None)
            break

        if native or ctx.get("audio_native"):
            b64 = audio_to_base64(audio)
            result = send_streaming(
                client, "", ctx,
                audio_data=b64, audio_format="wav", audio_native=True,
            )
        else:
            text = transcribe(audio, client, ctx)
            if text is None:
                if ctx.get("_wake_word_mode"):
                    continue
                console.print("  [dim]Voice conversation ended.[/dim]")
                ctx.pop("_voice_conversation", None)
                break
            console.print(f"  [dim]You said: {text}[/dim]")
            result = send_streaming(client, text, ctx)

        _handle_response(result, client, ctx)


def _exit_voice(ctx: dict) -> None:
    """Clean up voice mode flags on interrupt."""
    if ctx.get("_voice_conversation") or ctx.get("_wake_word_mode"):
        console.print("\n  [dim]Voice mode ended.[/dim]")
        ctx.pop("_voice_conversation", None)
        ctx.pop("_wake_word_mode", None)
