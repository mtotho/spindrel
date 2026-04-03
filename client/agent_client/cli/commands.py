"""Slash commands for the REPL."""
import base64
import json
import sys
import uuid
from pathlib import Path

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
from agent_client.state import (
    new_session_id,
    save_bot_id,
    save_channel_id,
    save_model_override,
    save_session_id,
)

from agent_client.cli.display import (
    console,
    format_last_active,
    print_error,
    print_status,
    print_warning,
    short_id,
)
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
        console.print("[dim]Multiple matches — selecting first:[/dim]")
        for s in choices:
            title = s.get("title") or "(untitled)"
            console.print(f"  [dim]{s['id'][:8]} {title} bot={s['bot_id']}[/dim]")
        return choices[0]
    return None


def handle_command(line: str, client: AgentClient, ctx: dict) -> bool:
    """Handle slash commands. Returns True if the input was a command."""
    parts = line.strip().split(maxsplit=1)
    cmd = parts[0].lower()

    if cmd in ("/quit", "/exit"):
        console.print("[dim]Goodbye.[/dim]")
        sys.exit(0)

    elif cmd == "/new":
        ctx["session_id"] = new_session_id()
        console.print(f"  New session: [bold]{ctx['session_id']}[/bold]")
        return True

    elif cmd == "/delete":
        return _cmd_delete(parts, client, ctx)

    elif cmd == "/session":
        return _cmd_session(parts, client, ctx)

    elif cmd == "/sessions":
        return _cmd_sessions(client, ctx)

    elif cmd == "/history":
        return _cmd_history(client, ctx)

    elif cmd == "/bots":
        return _cmd_bots(client, ctx)

    elif cmd == "/bot":
        if len(parts) < 2:
            console.print(f"  Current bot: [bold]{ctx['bot_id']}[/bold]")
        else:
            ctx["bot_id"] = parts[1]
            save_bot_id(parts[1])
            apply_bot_audio(client, ctx)
            audio_mode = "native" if ctx.get("audio_native") else "transcribe"
            console.print(f"  Switched to [bold]{ctx['bot_id']}[/bold] | audio {audio_mode}")
        return True

    elif cmd == "/channels":
        return _cmd_channels(client, ctx)

    elif cmd == "/channel":
        return _cmd_channel(parts, client, ctx)

    elif cmd == "/model":
        return _cmd_model(parts, ctx)

    elif cmd == "/attach":
        return _cmd_attach(parts, ctx)

    elif cmd == "/setup":
        return _cmd_setup(client)

    elif cmd == "/cancel":
        return _cmd_cancel(client, ctx)

    elif cmd in ("/v", "/voice"):
        if not STT_AVAILABLE:
            print_warning("Voice input not available. Install with: pip install -e 'client/[voice]'")
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
        print_status(f"You said: {text}")
        ctx["_voice_text"] = text
        return False

    elif cmd == "/vc":
        if not STT_AVAILABLE:
            print_warning("Voice input not available. Install with: pip install -e 'client/[voice]'")
            return True
        ctx["_voice_conversation"] = True
        console.print("  [dim]Voice conversation mode. Speak after each response. Stay silent or Ctrl+C to exit.[/dim]")
        audio = record_audio()
        if audio is None:
            ctx.pop("_voice_conversation", None)
            console.print("  [dim]Voice conversation ended.[/dim]")
            return True
        if ctx.get("audio_native"):
            ctx["_voice_audio"] = audio
            return False
        text = transcribe(audio, client, ctx)
        if text is None:
            ctx.pop("_voice_conversation", None)
            console.print("  [dim]Voice conversation ended.[/dim]")
            return True
        print_status(f"You said: {text}")
        ctx["_voice_text"] = text
        return False

    elif cmd == "/listen":
        if not WAKEWORD_AVAILABLE:
            print_warning("Wake word not available. Install with: pip install -e 'client/[wakeword]'")
            return True
        if not STT_AVAILABLE:
            print_warning("Voice input not available. Install with: pip install -e 'client/[voice]'")
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
        print_status(f"You said: {text}")
        ctx["_voice_text"] = text
        return False

    elif cmd == "/tts":
        if ctx["tts"]:
            ctx["tts"] = False
            console.print("  TTS [bold]off[/bold]")
        else:
            err = check_tts_ready(ctx["piper_model"], ctx["piper_model_dir"])
            if err:
                print_error(f"Cannot enable TTS: {err}")
            else:
                ctx["tts"] = True
                console.print("  TTS [bold]on[/bold]")
        return True

    elif cmd == "/tts_voice":
        if len(parts) < 2:
            console.print(f"  TTS voice: [bold]{ctx['piper_model']}[/bold]")
        else:
            model = parts[1]
            err = check_tts_ready(model, ctx["piper_model_dir"])
            if err:
                print_error(f"Cannot use that voice: {err}")
            else:
                ctx["piper_model"] = model
                console.print(f"  TTS voice: [bold]{model}[/bold]")
        return True

    elif cmd == "/tone":
        presets = ("chime", "beep", "ping")
        if len(parts) < 2:
            console.print(f"  Listen tone: [bold]{ctx.get('listen_sound', 'chime')}[/bold]")
        else:
            preset = parts[1].lower()
            if preset in presets:
                ctx["listen_sound"] = preset
                console.print(f"  Listen tone: [bold]{preset}[/bold]")
            else:
                print_error(f"Unknown preset. Use one of: {', '.join(presets)}")
        return True

    elif cmd == "/compact":
        try:
            print_status("Compacting session...")
            result = client.summarize_session(ctx["session_id"])
            console.print(f"  Title: [bold]{result.get('title', '(none)')}[/bold]")
            summary = result.get("summary", "")
            if len(summary) > 200:
                summary = summary[:200] + "..."
            console.print(f"  [dim]{summary}[/dim]")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                print_error("Session not found on server (send a message first).")
            elif e.response.status_code == 400:
                print_error("Nothing to summarize yet.")
            else:
                print_error(f"Error: {e}")
        except httpx.HTTPError as e:
            print_error(f"Error: {e}")
        return True

    elif cmd == "/audio":
        ctx["audio_native"] = not ctx.get("audio_native", False)
        state = "native" if ctx["audio_native"] else "transcribe"
        console.print(f"  Audio input mode: [bold]{state}[/bold]")
        return True

    elif cmd == "/verbose":
        ctx["_verbose"] = not ctx.get("_verbose", False)
        state = "on" if ctx["_verbose"] else "off"
        console.print(f"  Verbose context events: [bold]{state}[/bold]")
        return True

    elif cmd == "/tools":
        return _cmd_tools(client)

    elif cmd == "/tool":
        return _cmd_tool(parts, client)

    elif cmd == "/help":
        return _cmd_help()

    return False


# --- Command implementations ---


def _cmd_delete(parts: list[str], client: AgentClient, ctx: dict) -> bool:
    try:
        sessions = client.list_sessions()
        if not sessions:
            console.print("  No sessions to delete.")
            return True

        from rich.table import Table
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        table.add_column("#", style="dim", width=4)
        table.add_column("ID", width=8)
        table.add_column("Title", max_width=30)
        table.add_column("Bot")
        table.add_column("Last Active", style="dim")
        for i, s in enumerate(sessions):
            title = (s.get("title") or "(untitled)")[:30]
            last = format_last_active(s.get("last_active", ""))
            table.add_row(str(i + 1), s["id"][:8], title, s["bot_id"], last)
        console.print(table)

        delete_num = None
        if len(parts) >= 2 and parts[1].strip().isdigit():
            delete_num = int(parts[1].strip())
        else:
            try:
                user_in = console.input("  Enter the number of the session to delete: ").strip()
            except (EOFError, KeyboardInterrupt):
                return True
            if not user_in.isdigit():
                print_error("Invalid number.")
                return True
            delete_num = int(user_in)

        index = delete_num - 1
        if index < 0 or index >= len(sessions):
            print_error("Invalid session number.")
            return True

        session_id = sessions[index]["id"]
        client.delete_session(uuid.UUID(session_id))
        console.print(f"  Session {session_id[:8]} deleted.")

        if session_id == str(ctx["session_id"]):
            ctx["session_id"] = new_session_id()
            console.print(f"  Created new session: [bold]{ctx['session_id']}[/bold]")
            save_session_id(ctx["session_id"])
    except Exception as e:
        print_error(f"Error deleting session: {e}")
    return True


def _cmd_session(parts: list[str], client: AgentClient, ctx: dict) -> bool:
    if len(parts) < 2:
        console.print(f"  Current session: [bold]{ctx['session_id']}[/bold]")
        return True
    try:
        sessions = client.list_sessions()
        raw = parts[1]
        if raw.isdigit():
            index = int(raw) - 1
            if 0 <= index < len(sessions):
                ctx["session_id"] = sessions[index]["id"]
                save_session_id(ctx["session_id"])
                title = sessions[index].get("title") or "(untitled)"
                console.print(f"  Switched to session: [bold]{str(ctx['session_id'])[:8]}[/bold] {title}")
            else:
                print_error("Invalid session number.")
            return True
        try:
            sid = uuid.UUID(raw)
            found = any(str(s["id"]) == str(sid) for s in sessions)
            if found:
                ctx["session_id"] = sid
                save_session_id(sid)
                console.print(f"  Switched to session: [bold]{sid}[/bold]")
            else:
                print_error("Session with this UUID not found.")
        except ValueError:
            found = _fuzzy_find_session(sessions, raw)
            if found:
                ctx["session_id"] = uuid.UUID(found["id"])
                save_session_id(ctx["session_id"])
                console.print(f"  Switched to session: [bold]{found['id'][:8]}[/bold] ({found.get('title', '(untitled)')})")
            else:
                print_error("No session found matching identifier or title.")
    except Exception as e:
        print_error(f"Error looking up session: {e}")
    return True


def _cmd_sessions(client: AgentClient, ctx: dict) -> bool:
    try:
        sessions = client.list_sessions()
        if not sessions:
            console.print("  No sessions.")
            return True

        from rich.table import Table
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        table.add_column("#", style="dim", width=4)
        table.add_column("ID", width=8)
        table.add_column("Title", max_width=30)
        table.add_column("Bot")
        table.add_column("Client", style="dim")
        table.add_column("Last Active", style="dim")
        table.add_column("", width=3)

        for i, s in enumerate(sessions):
            selected = str(ctx["session_id"]) == s["id"]
            marker = "[bold green]*[/bold green]" if selected else ""
            title = (s.get("title") or "(untitled)")[:30]
            last = format_last_active(s.get("last_active", ""))
            style = "bold" if selected else ""
            table.add_row(str(i + 1), s["id"][:8], title, s["bot_id"], s.get("client_id", ""), last, marker, style=style)
        console.print(table)
        console.print("  [dim]Switch with /session <number|id|title>[/dim]")
    except httpx.HTTPError as e:
        print_error(f"Error listing sessions: {e}")
    return True


def _cmd_history(client: AgentClient, ctx: dict) -> bool:
    try:
        data = client.get_session(ctx["session_id"])
        from rich.markdown import Markdown
        from rich.padding import Padding
        from rich.rule import Rule
        for msg in data["messages"]:
            role = msg["role"].upper()
            content = msg.get("content", "")
            if role == "SYSTEM":
                continue
            if role == "TOOL":
                continue
            if role == "USER":
                console.print(Rule(f"[bold blue]You[/bold blue]", style="blue"))
                console.print(Padding(content, (0, 2)))
            elif role == "ASSISTANT":
                console.print(Rule(f"[bold green]Assistant[/bold green]", style="green"))
                console.print(Padding(Markdown(content), (0, 2)))
            else:
                console.print(f"  [dim]{role}[/dim] {content}")
        console.print()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            console.print("  [dim]No history yet for this session.[/dim]")
        else:
            print_error(f"Error: {e}")
    except httpx.HTTPError as e:
        print_error(f"Error: {e}")
    return True


def _cmd_bots(client: AgentClient, ctx: dict) -> bool:
    try:
        bots = client.list_bots()
        if not bots:
            console.print("  No bots configured.")
            return True

        from rich.table import Table
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        table.add_column("ID")
        table.add_column("Name")
        table.add_column("Model", style="dim")
        table.add_column("", width=3)

        for b in bots:
            marker = "[bold green]*[/bold green]" if ctx["bot_id"] == b["id"] else ""
            style = "bold" if ctx["bot_id"] == b["id"] else ""
            table.add_row(b["id"], b["name"], b["model"], marker, style=style)
        console.print(table)
    except httpx.HTTPError as e:
        print_error(f"Error listing bots: {e}")
    return True


def _cmd_channels(client: AgentClient, ctx: dict) -> bool:
    try:
        data = client.list_channels(bot_id=ctx["bot_id"])
        channels = data.get("channels", [])
        if not channels:
            console.print("  No channels.")
            return True

        from rich.table import Table
        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        table.add_column("#", style="dim", width=4)
        table.add_column("ID", width=8)
        table.add_column("Name", max_width=30)
        table.add_column("Bot")
        table.add_column("Integration", style="dim")
        table.add_column("", width=3)

        current = ctx.get("channel_id")
        for i, ch in enumerate(channels):
            ch_id = ch["id"]
            selected = current and str(current) == str(ch_id)
            marker = "[bold green]*[/bold green]" if selected else ""
            name = ch.get("name") or ch.get("display_name") or "(unnamed)"
            integration = ch.get("integration") or ""
            style = "bold" if selected else ""
            table.add_row(str(i + 1), str(ch_id)[:8], name[:30], ch.get("bot_id", ""), integration, marker, style=style)
        console.print(table)
        console.print(f"  [dim]{data.get('total', len(channels))} channels. Switch with /channel <number|id>[/dim]")
    except httpx.HTTPError as e:
        print_error(f"Error listing channels: {e}")
    return True


def _cmd_channel(parts: list[str], client: AgentClient, ctx: dict) -> bool:
    if len(parts) < 2:
        ch = ctx.get("channel_id")
        if ch:
            console.print(f"  Current channel: [bold]{short_id(ch)}[/bold]")
        else:
            console.print("  No channel set. Use /channels to list, /channel <id> to switch.")
        return True

    arg = parts[1].strip()
    if arg.lower() == "none":
        ctx["channel_id"] = None
        save_channel_id(None)
        console.print("  Channel cleared.")
        return True

    try:
        data = client.list_channels(bot_id=ctx["bot_id"])
        channels = data.get("channels", [])

        if arg.isdigit():
            index = int(arg) - 1
            if 0 <= index < len(channels):
                ch = channels[index]
                ctx["channel_id"] = ch["id"]
                save_channel_id(ch["id"])
                name = ch.get("name") or ch.get("display_name") or "(unnamed)"
                console.print(f"  Switched to channel: [bold]{short_id(ch['id'])}[/bold] {name}")
            else:
                print_error("Invalid channel number.")
            return True

        # Try UUID match
        for ch in channels:
            if str(ch["id"]).startswith(arg) or str(ch["id"]) == arg:
                ctx["channel_id"] = ch["id"]
                save_channel_id(ch["id"])
                name = ch.get("name") or ch.get("display_name") or "(unnamed)"
                console.print(f"  Switched to channel: [bold]{short_id(ch['id'])}[/bold] {name}")
                return True

        # Try name match
        for ch in channels:
            name = ch.get("name") or ch.get("display_name") or ""
            if arg.lower() in name.lower():
                ctx["channel_id"] = ch["id"]
                save_channel_id(ch["id"])
                console.print(f"  Switched to channel: [bold]{short_id(ch['id'])}[/bold] {name}")
                return True

        print_error(f"No channel found matching '{arg}'.")
    except httpx.HTTPError as e:
        print_error(f"Error: {e}")
    return True


def _cmd_model(parts: list[str], ctx: dict) -> bool:
    """Set per-turn model override.  /model provider_id:model_name  or  /model model_name"""
    if len(parts) < 2:
        current = ctx.get("model_override")
        pid = ctx.get("model_provider_id_override")
        if current:
            display = f"{pid}:{current}" if pid else current
            console.print(f"  Model override: [bold]{display}[/bold]")
        else:
            console.print("  No model override. Use /model [provider:]<name> to set, /model reset to clear.")
        return True

    arg = parts[1].strip()
    if arg.lower() == "reset":
        ctx["model_override"] = None
        ctx["model_provider_id_override"] = None
        save_model_override(None)
        console.print("  Model override cleared.")
    else:
        # Support provider_id:model syntax for explicit provider pairing.
        # Provider IDs are simple slugs (no slashes), so "ollama/llama3:8b"
        # is a model with a tag, not a provider:model pair.
        first_colon = arg.find(":")
        if first_colon > 0 and "/" not in arg[:first_colon] and not arg.startswith("http"):
            provider_id, model = arg[:first_colon], arg[first_colon + 1:]
        else:
            provider_id, model = None, arg
        ctx["model_override"] = model
        ctx["model_provider_id_override"] = provider_id
        save_model_override(model, provider_id)
        display = f"{provider_id}:{model}" if provider_id else model
        console.print(f"  Model override: [bold]{display}[/bold]")
    return True


def _cmd_attach(parts: list[str], ctx: dict) -> bool:
    if len(parts) < 2:
        pending = ctx.get("_attachments", [])
        if pending:
            console.print(f"  {len(pending)} attachment(s) queued for next message.")
        else:
            console.print("  Usage: /attach <path> — queue an image for next message")
        return True

    path = Path(parts[1].strip()).expanduser()
    if not path.is_file():
        print_error(f"File not found: {path}")
        return True

    suffix = path.suffix.lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp"}
    mime = mime_map.get(suffix)
    if not mime:
        print_error(f"Unsupported file type: {suffix}. Supported: {', '.join(mime_map)}")
        return True

    data = base64.b64encode(path.read_bytes()).decode()
    attachment = {"type": "image", "mime_type": mime, "data": data, "filename": path.name}

    if "_attachments" not in ctx:
        ctx["_attachments"] = []
    ctx["_attachments"].append(attachment)
    console.print(f"  Attached [bold]{path.name}[/bold] ({len(data) // 1024}KB). Will send with next message.")
    return True


def _cmd_setup(client: AgentClient) -> bool:
    console.print("  Creating scoped API key for CLI client...")
    scopes = ["chat", "sessions:read", "sessions:write", "bots:read", "tools:read",
              "tools:execute", "tasks:read", "channels:read", "approvals:write"]
    try:
        result = client.create_api_key("cli-client", scopes)
        full_key = result.get("full_key", "")
        console.print(f"\n  [bold green]API key created![/bold green]")
        console.print(f"  Key: [bold]{full_key}[/bold]")
        console.print(f"  Scopes: {', '.join(scopes)}")
        console.print(f"\n  [yellow]Save this key — it won't be shown again.[/yellow]")
        console.print(f"  Add to ~/.config/agent-client/config.env:")
        console.print(f"  [dim]API_KEY={full_key}[/dim]")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 422:
            print_error(f"Validation error: {e.response.text[:200]}")
        else:
            print_error(f"Error: {e.response.status_code}")
    except httpx.HTTPError as e:
        print_error(f"Error: {e}")
    return True


def _cmd_cancel(client: AgentClient, ctx: dict) -> bool:
    try:
        result = client.cancel(ctx["bot_id"], ctx.get("client_id", "cli"))
        if result.get("cancelled"):
            console.print("  [bold]Cancelled.[/bold]")
        else:
            queued = result.get("queued_tasks_cancelled", 0)
            if queued:
                console.print(f"  Cancelled {queued} queued task(s).")
            else:
                console.print("  [dim]Nothing to cancel.[/dim]")
    except httpx.HTTPError as e:
        print_error(f"Error: {e}")
    return True


def _cmd_tools(client: AgentClient) -> bool:
    try:
        tools = client.list_tools()
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
        console.print(f"  [dim]{len(tools)} tools. Use /tool <name> [json args] to execute.[/dim]")
    except httpx.HTTPError as e:
        print_error(f"Error listing tools: {e}")
    return True


def _cmd_tool(parts: list[str], client: AgentClient) -> bool:
    if len(parts) < 2:
        console.print("  Usage: /tool <tool_name> [json args]")
        return True
    rest = parts[1].strip()
    space_idx = rest.find(" ")
    if space_idx == -1:
        tool_name = rest
        tool_args = {}
    else:
        tool_name = rest[:space_idx]
        try:
            tool_args = json.loads(rest[space_idx + 1:])
        except json.JSONDecodeError:
            print_error(f"Cannot parse arguments as JSON: {rest[space_idx + 1:]}")
            return True
    try:
        result = client.execute_tool(tool_name, tool_args)
        if result.get("error"):
            print_error(result["error"])
        out = result.get("result")
        if isinstance(out, (dict, list)):
            from rich.syntax import Syntax
            console.print(Syntax(json.dumps(out, indent=2), "json"))
        else:
            console.print(str(out))
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            print_error(f"Tool '{tool_name}' not found (only local tools supported).")
        else:
            print_error(f"Error: {e.response.status_code}")
    except httpx.HTTPError as e:
        print_error(f"Error: {e}")
    return True


def _cmd_help() -> bool:
    from rich.table import Table
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
    table.add_column("Command", style="bold")
    table.add_column("Description")

    commands = [
        ("/new", "Start a new session"),
        ("/session [id]", "Show or switch session"),
        ("/sessions", "List all sessions"),
        ("/history", "Show current session history"),
        ("/compact", "Force context compaction"),
        ("/channels", "List channels"),
        ("/channel [id]", "Show or switch channel (/channel none to clear)"),
        ("/model [name|reset]", "Set or clear model override"),
        ("/attach <path>", "Queue image attachment for next message"),
        ("/cancel", "Cancel in-progress request"),
        ("/setup", "Generate a scoped API key for this client"),
        ("/delete [n]", "Delete a session"),
        ("/verbose", "Toggle verbose context assembly events"),
        ("", ""),
        ("/bots", "List available bots"),
        ("/bot [id]", "Show or switch bot"),
        ("/tools", "List all server tools"),
        ("/tool <name> [json]", "Execute a tool directly"),
        ("", ""),
        ("/v", "Voice input (single turn)"),
        ("/vc", "Voice conversation (continuous)"),
        ("/listen", "Wake word mode"),
        ("/tts", "Toggle text-to-speech"),
        ("/tts_voice [model]", "Get or set TTS voice"),
        ("/tone [preset]", "Get or set listen tone (chime|beep|ping)"),
        ("/audio", "Toggle native audio mode"),
        ("", ""),
        ("/quit", "Exit (Ctrl+C also works)"),
    ]
    for cmd, desc in commands:
        if not cmd:
            table.add_row("", "")
        else:
            table.add_row(cmd, desc)
    console.print(table)
    return True
