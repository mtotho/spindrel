"""Slash commands: /bot, /bots, /ask, /context, /compact, /todos, /health."""

import asyncio
import json
import logging
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from agent_client import (
    ensure_channel,
    fetch_server_health,
    fetch_session_context_contents,
    get_channel_session_id,
    list_bots,
    list_models,
    submit_chat,
)
from formatting import format_last_active, split_for_slack
from integrations.slash_command_client import (
    SlashCommandAskTarget,
    SlashCommandClient,
    SlashCommandClientError,
    format_ask_target_options,
    resolve_ask_target,
)
from message_handlers import _resolve_slack_display_name
from session_helpers import slack_client_id
from slack_settings import AGENT_BASE_URL, API_KEY, BOT_TOKEN, get_bot_display_info
from state import get_channel_state, get_global_setting, set_channel_state, set_global_setting

logger = logging.getLogger(__name__)
_slash_client = SlashCommandClient(AGENT_BASE_URL, API_KEY)


async def _resolve_session_id(channel: str, bot_id: str) -> str | None:
    """Look up the active session_id for a Slack channel from the server."""
    return await get_channel_session_id(channel, bot_id)


async def _respond_backend_command(
    *,
    respond,
    channel: str,
    bot_id: str,
    command_id: str,
    args: list[str] | None = None,
) -> None:
    try:
        result = await _slash_client.execute_for_client_channel(
            client_id=slack_client_id(channel),
            bot_id=bot_id,
            command_id=command_id,
            args=args or [],
        )
    except SlashCommandClientError as exc:
        await respond(f"Error: {exc}")
        return
    text = result.fallback_text or "(no result)"
    for chunk in split_for_slack(text, limit=3000):
        await respond(chunk)


async def _ask_targets_for_channel(channel: str, bot_id: str) -> list[SlashCommandAskTarget]:
    return await _slash_client.list_channel_ask_targets(
        client_id=slack_client_id(channel),
        bot_id=bot_id,
    )


def _plain_text(text: str, *, limit: int = 75) -> str:
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def _ask_modal_view(channel: str, user: str, targets: list[SlashCommandAskTarget]) -> dict:
    return {
        "type": "modal",
        "callback_id": "spindrel_ask_bot",
        "title": {"type": "plain_text", "text": "Ask bot"},
        "submit": {"type": "plain_text", "text": "Send"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": json.dumps({"channel": channel, "user": user}),
        "blocks": [
            {
                "type": "input",
                "block_id": "target",
                "label": {"type": "plain_text", "text": "Bot"},
                "element": {
                    "type": "static_select",
                    "action_id": "bot_id",
                    "options": [
                        {
                            "text": {
                                "type": "plain_text",
                                "text": _plain_text(
                                    f"{target.label} ({'primary' if target.is_primary else 'member'})"
                                ),
                            },
                            "value": str(index),
                        }
                        for index, target in enumerate(targets)
                    ],
                },
            },
            {
                "type": "input",
                "block_id": "message",
                "label": {"type": "plain_text", "text": "Message"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "text",
                    "multiline": True,
                },
            },
        ],
    }


async def _submit_slack_ask(
    *,
    client,
    channel: str,
    user: str,
    target: SlashCommandAskTarget,
    message: str,
) -> None:
    sender_display_name = await _resolve_slack_display_name(client, user)
    msg_metadata = {
        "passive": False,
        "source": "slack",
        "sender_type": "human",
        "sender_id": f"slack:{user}",
        "sender_display_name": sender_display_name,
        "channel_external_id": channel,
        "mention_token": f"<@{user}>",
        "recipient_id": f"bot:{target.bot_id}",
        "trigger_rag": True,
    }
    dispatch_config = {
        "channel_id": channel,
        "thread_ts": None,
        "token": BOT_TOKEN,
    }
    await submit_chat(
        message=message,
        bot_id=target.bot_id,
        client_id=slack_client_id(channel),
        dispatch_type="slack",
        dispatch_config=dispatch_config,
        msg_metadata=msg_metadata,
    )


def register_slash_commands(app):
    @app.command("/bot")
    async def cmd_bot(ack, command, respond):
        await ack()
        channel = command.get("channel_id") or ""
        arg = (command.get("text") or "").strip()

        if not arg:
            state = get_channel_state(channel)
            # Ensure Channel row exists on the server
            await ensure_channel(slack_client_id(channel), state["bot_id"])
            await respond(f"Current bot: `{state['bot_id']}`")
            return

        valid = {b["id"] for b in await list_bots()}

        if arg not in valid:
            await respond(f"Unknown bot. Available: {', '.join(sorted(valid))}")
            return

        set_channel_state(channel, bot_id=arg)
        # Ensure Channel row exists on the server for this Slack channel
        await ensure_channel(slack_client_id(channel), arg)
        await respond(f"Switched to `{arg}`.")

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

    @app.command("/ask")
    async def cmd_ask(ack, command, client, respond):
        """Route a message to a channel participant: /ask <bot-id> <message>"""
        await ack()
        channel = command.get("channel_id") or ""
        user = command.get("user_id") or "unknown"
        text = (command.get("text") or "").strip()
        state = get_channel_state(channel)

        try:
            targets = await _ask_targets_for_channel(channel, state["bot_id"])
        except SlashCommandClientError as exc:
            await respond(f"Error: {exc}")
            return

        if not text:
            trigger_id = command.get("trigger_id")
            if trigger_id:
                try:
                    await client.views_open(
                        trigger_id=trigger_id,
                        view=_ask_modal_view(channel, user, targets),
                    )
                    return
                except Exception:
                    logger.exception("Failed to open Slack /ask modal for channel %s", channel)
            await respond(format_ask_target_options(targets, command="/ask"))
            return

        parts = text.split(None, 1)
        if len(parts) < 2:
            await respond(format_ask_target_options(targets, command="/ask"))
            return

        target = resolve_ask_target(targets, parts[0])
        message = parts[1].strip()

        if not message:
            await respond("Please provide a message after the bot ID.")
            return

        if not target:
            await respond(
                f"Unknown bot `{parts[0]}` for this channel.\n"
                f"{format_ask_target_options(targets, command='/ask')}"
            )
            return

        try:
            await _submit_slack_ask(
                client=client,
                channel=channel,
                user=user,
                target=target,
                message=message,
            )
            await respond(f"Queued request for `{target.bot_id}`.")
        except Exception as e:
            logger.exception("submit_chat failed for /ask in channel %s", channel)
            try:
                await client.chat_postMessage(
                    channel=channel,
                    text=f"_Failed to enqueue request: {str(e)[:200]}_",
                )
            except Exception:
                pass

    @app.view("spindrel_ask_bot")
    async def handle_ask_modal(ack, body, client, view):
        values = view.get("state", {}).get("values", {})
        selected = (
            values.get("target", {})
            .get("bot_id", {})
            .get("selected_option", {})
            .get("value")
        )
        message = (
            values.get("message", {})
            .get("text", {})
            .get("value")
            or ""
        ).strip()
        if not message:
            await ack(response_action="errors", errors={"message": "Message is required."})
            return
        await ack()

        metadata = {}
        try:
            metadata = json.loads(view.get("private_metadata") or "{}")
        except Exception:
            pass
        channel = str(metadata.get("channel") or "")
        user = str(metadata.get("user") or body.get("user", {}).get("id") or "unknown")
        if not channel or not selected:
            return

        state = get_channel_state(channel)
        try:
            targets = await _ask_targets_for_channel(channel, state["bot_id"])
            selected_index = int(selected) if selected.isdigit() else -1
            target = targets[selected_index] if 0 <= selected_index < len(targets) else None
            if not target:
                await client.chat_postEphemeral(
                    channel=channel,
                    user=user,
                    text=f"`{selected}` is not a bot target in this channel.",
                )
                return
            await _submit_slack_ask(
                client=client,
                channel=channel,
                user=user,
                target=target,
                message=message,
            )
            await client.chat_postEphemeral(
                channel=channel,
                user=user,
                text=f"Queued request for `{target.bot_id}`.",
            )
        except Exception as exc:
            logger.exception("Slack /ask modal submit failed for channel %s", channel)
            try:
                await client.chat_postEphemeral(
                    channel=channel,
                    user=user,
                    text=f"Failed to enqueue request: {str(exc)[:200]}",
                )
            except Exception:
                pass

    @app.command("/context")
    async def cmd_context(ack, command, respond):
        await ack()
        subcommand = (command.get("text") or "").strip().lower()
        channel = command.get("channel_id") or ""
        state = get_channel_state(channel)
        session_id = await _resolve_session_id(channel, state["bot_id"])
        if not session_id:
            await respond("No active session for this channel yet. Send a message first.")
            return

        # /context contents — dump actual messages the model would see
        if subcommand == "contents":
            await respond("_Running compression and fetching context contents..._")
            try:
                data = await fetch_session_context_contents(session_id, compress=True)
            except Exception as e:
                await respond(f"Error: {e}")
                return
            compressed = data.get("compressed", False)
            total = data.get("total_messages", 0)
            chars = data.get("total_chars", 0)
            header = f"*Context Contents* — {total} messages / {chars:,} chars"
            if compressed:
                header += " _(compressed)_"
            lines = [header]
            for i, m in enumerate(data.get("messages", [])):
                role = m.get("role", "?")
                content = m.get("content") or ""
                if isinstance(content, list):
                    content = " ".join(str(p) for p in content)
                # Truncate long content for Slack readability
                if len(content) > 300:
                    content = content[:300] + "…"
                content = content.replace("\n", " ↵ ")
                tc = ""
                if m.get("tool_calls"):
                    names = [tc.get("function", {}).get("name", "?") for tc in m["tool_calls"]]
                    tc = f" → [{', '.join(names)}]"
                tid = ""
                if m.get("tool_call_id"):
                    tid = f" (call_id={m['tool_call_id'][:8]}…)"
                lines.append(f"`[{i}] {role}{tid}:` {content}{tc}")
            # Slack has a 3000 char limit per message — split if needed
            text = "\n".join(lines)
            for chunk in split_for_slack(text, limit=3000):
                await respond(chunk)
            return

        await _respond_backend_command(
            respond=respond,
            channel=channel,
            bot_id=state["bot_id"],
            command_id="context",
        )

    @app.command("/compact")
    async def cmd_compact(ack, command, respond):
        await ack()
        channel = command.get("channel_id") or ""
        state = get_channel_state(channel)
        await _respond_backend_command(
            respond=respond,
            channel=channel,
            bot_id=state["bot_id"],
            command_id="compact",
        )

    @app.command("/todos")
    async def cmd_todos(ack, command, respond):
        """Deprecated legacy todo command."""
        await ack()
        await respond("`/todos` is retired. Use the channel Todo widget in Spindrel instead.")

    @app.command("/health")
    async def cmd_status(ack, command, respond):
        """Quick server health check — host services + agent server API health."""
        await ack()

        async def _run(cmd: str, timeout: float = 5.0) -> str:
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                return stdout.decode("utf-8", errors="replace").strip()
            except asyncio.TimeoutError:
                return "⚠️ timed out"
            except Exception as e:
                return f"⚠️ {e}"

        # Run host checks and server health concurrently.
        host_results, server_health = await asyncio.gather(
            asyncio.gather(
                _run("systemctl is-active spindrel spindrel-slack 2>/dev/null || echo 'unknown'"),
                _run("docker ps --format '{{.Names}}\\t{{.Status}}' 2>/dev/null | grep -E 'postgres|searxng|playwright' || echo 'none running'"),
                _run("df -h / | tail -1"),
                _run("tail -1 ~/logs/backup.log 2>/dev/null || echo 'no log'"),
            ),
            fetch_server_health(),
        )
        svc_raw, docker_raw, disk_raw, backup_raw = host_results

        lines: list[str] = ["*Server Status*", ""]

        # Server health (from API)
        srv_icon = "✅" if server_health.get("healthy") else "🚨"
        lines.append(f"*Agent Server* {srv_icon}")
        if server_health.get("database") is not None:
            db_icon = "✅" if server_health["database"] else "🚨"
            lines.append(f"  {db_icon} Database")
        uptime = server_health.get("uptime_seconds")
        if uptime is not None:
            h, m = divmod(uptime // 60, 60)
            lines.append(f"  Uptime: {h}h {m}m")
        bots_count = server_health.get("bot_count")
        if bots_count is not None:
            lines.append(f"  Bots: {bots_count}")
        version = server_health.get("version")
        if version:
            lines.append(f"  Version: `{version[:120]}`")
        for issue in server_health.get("issues", []):
            lines.append(f"  🚨 {issue}")

        # Host services
        svc_lines = svc_raw.splitlines()
        svc_names = ["spindrel", "spindrel-slack"]
        svc_parts: list[str] = []
        for i, name in enumerate(svc_names):
            status = svc_lines[i].strip() if i < len(svc_lines) else "unknown"
            icon = "✅" if status == "active" else "🚨"
            svc_parts.append(f"{icon} `{name}`: {status}")
        lines.append("\n*Services*")
        lines.extend(f"  {s}" for s in svc_parts)

        # Docker containers
        lines.append("\n*Containers*")
        if "none" in docker_raw:
            lines.append("  🚨 No matching containers running")
        else:
            for row in docker_raw.splitlines():
                parts = row.split("\t", 1)
                name = parts[0] if parts else row
                st = parts[1] if len(parts) > 1 else ""
                icon = "✅" if "Up" in st else "🚨"
                lines.append(f"  {icon} `{name}`: {st}")

        # Disk
        lines.append("\n*Disk*")
        try:
            disk_parts = disk_raw.split()
            use_pct = int(disk_parts[4].rstrip("%")) if len(disk_parts) >= 5 else 0
            icon = "🚨" if use_pct > 90 else ("⚠️" if use_pct > 80 else "✅")
            lines.append(f"  {icon} `/`: {disk_parts[4]} used ({disk_parts[3]} avail)")
        except (IndexError, ValueError):
            lines.append(f"  ⚠️ `{disk_raw}`")

        # Backup
        lines.append("\n*Last Backup*")
        lines.append(f"  {backup_raw[:200]}")

        await respond("\n".join(lines))

    @app.command("/model")
    async def cmd_model(ack, command, respond):
        """View or change the model override for this channel."""
        await ack()
        channel = command.get("channel_id") or ""
        state = get_channel_state(channel)
        bot_id = state["bot_id"]
        arg = (command.get("text") or "").strip()

        # /model list — show available models
        if arg.lower() == "list":
            try:
                groups = await list_models()
            except Exception as e:
                await respond(f"Error fetching models: {e}")
                return
            lines = ["*Available Models*"]
            for g in groups:
                provider = g.get("provider_name", "Unknown")
                models = g.get("models", [])
                if not models:
                    continue
                lines.append(f"\n*{provider}*")
                for m in models:
                    lines.append(f"  `{m['id']}`")
            await respond("\n".join(lines))
            return

        await _respond_backend_command(
            respond=respond,
            channel=channel,
            bot_id=bot_id,
            command_id="model",
            args=[arg] if arg else [],
        )

    @app.command("/audit")
    async def cmd_audit(ack, command, respond):
        """Set or clear the audit channel for tool call logging."""
        await ack()
        arg = (command.get("text") or "").strip()

        if not arg:
            current = get_global_setting("audit_channel")
            if current:
                await respond(f"Audit channel: <#{current}>\nUse `/audit off` to disable.")
            else:
                await respond("No audit channel set.\nUsage: `/audit #channel` or `/audit off`")
            return

        if arg.lower() == "off":
            set_global_setting("audit_channel", None)
            await respond("Audit logging disabled.")
            return

        # Accept <#C12345|channel-name> format (Slack's channel mention) or raw ID
        channel_id = arg
        if arg.startswith("<#") and "|" in arg:
            channel_id = arg.split("|")[0].lstrip("<#")
        elif arg.startswith("<#"):
            channel_id = arg.strip("<#>")

        set_global_setting("audit_channel", channel_id)
        await respond(f"Audit channel set to <#{channel_id}>.\nTool calls across all bots will be logged there.")
