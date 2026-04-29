"""Discord application commands: /bot, /bots, /ask, /context, /compact, /model, /health, /audit."""
import asyncio
import logging
import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import discord
from discord import app_commands

from agent_client import (
    ensure_channel,
    fetch_server_health,
    fetch_session_context_contents,
    get_channel_session_id,
    list_bots,
    list_models,
    submit_chat,
)
from formatting import format_last_active, split_for_discord
from integrations.slash_command_client import (
    SlashCommandAskTarget,
    SlashCommandClient,
    SlashCommandClientError,
    format_ask_target_options,
    resolve_ask_target,
)
from session_helpers import discord_client_id
from discord_settings import AGENT_BASE_URL, API_KEY, DISCORD_TOKEN, get_bot_display_info
from state import get_channel_state, get_global_setting, set_channel_state, set_global_setting

logger = logging.getLogger(__name__)
_slash_client = SlashCommandClient(AGENT_BASE_URL, API_KEY)

async def _resolve_session_id(channel_id: str, bot_id: str) -> str | None:
    """Look up the active session_id for a Discord channel from the server."""
    return await get_channel_session_id(channel_id, bot_id)


async def _send_chunks(interaction: discord.Interaction, text: str) -> None:
    """Send a potentially long response, splitting for Discord's 2000 char limit."""
    chunks = split_for_discord(text)
    if not chunks:
        return
    await interaction.followup.send(chunks[0])
    for chunk in chunks[1:]:
        await interaction.followup.send(chunk)


async def _send_backend_command(
    *,
    interaction: discord.Interaction,
    channel_id: str,
    bot_id: str,
    command_id: str,
    args: list[str] | None = None,
) -> None:
    try:
        result = await _slash_client.execute_for_client_channel(
            client_id=discord_client_id(channel_id),
            bot_id=bot_id,
            command_id=command_id,
            args=args or [],
        )
    except SlashCommandClientError as exc:
        await interaction.followup.send(f"Error: {exc}")
        return
    await _send_chunks(interaction, result.fallback_text or "(no result)")


async def _ask_targets_for_channel(channel_id: str, bot_id: str) -> list[SlashCommandAskTarget]:
    return await _slash_client.list_channel_ask_targets(
        client_id=discord_client_id(channel_id),
        bot_id=bot_id,
    )


async def _ask_bot_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    channel_id = str(interaction.channel_id)
    state = get_channel_state(channel_id)
    try:
        targets = await _ask_targets_for_channel(channel_id, state["bot_id"])
    except Exception:
        return []

    query = current.lower().strip()
    choices: list[app_commands.Choice[str]] = []
    for target in targets:
        label = f"{target.label} ({'primary' if target.is_primary else 'member'})"
        if query and query not in target.bot_id.lower() and query not in target.label.lower():
            continue
        choices.append(app_commands.Choice(name=label[:100], value=target.bot_id[:100]))
        if len(choices) >= 25:
            break
    return choices


def register_slash_commands(tree: app_commands.CommandTree) -> None:
    """Register all Discord application commands on the command tree."""

    @tree.command(name="bot", description="View or switch the active bot for this channel")
    @app_commands.describe(bot_id="Bot ID to switch to (leave empty to see current)")
    async def cmd_bot(interaction: discord.Interaction, bot_id: str | None = None):
        await interaction.response.defer(ephemeral=True)
        channel_id = str(interaction.channel_id)

        if not bot_id:
            state = get_channel_state(channel_id)
            await ensure_channel(discord_client_id(channel_id), state["bot_id"])
            await interaction.followup.send(f"Current bot: `{state['bot_id']}`")
            return

        valid = {b["id"] for b in await list_bots()}
        if bot_id not in valid:
            await interaction.followup.send(f"Unknown bot. Available: {', '.join(sorted(valid))}")
            return

        set_channel_state(channel_id, bot_id=bot_id)
        await ensure_channel(discord_client_id(channel_id), bot_id)
        await interaction.followup.send(f"Switched to `{bot_id}`.")

    @tree.command(name="bots", description="List all available bots")
    async def cmd_bots(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel_id = str(interaction.channel_id)
        bots_list = await list_bots()
        current = get_channel_state(channel_id)["bot_id"]
        lines = [
            f"{'**' if b['id'] == current else '  '}`{b['id']}` \u2014 {b['name']} ({b['model']}){'**' if b['id'] == current else ''}"
            for b in bots_list
        ]
        await interaction.followup.send("\n".join(lines))

    @tree.command(name="ask", description="Route a message to a specific bot")
    @app_commands.describe(bot_id="Target channel bot", message="Message to send")
    @app_commands.autocomplete(bot_id=_ask_bot_autocomplete)
    async def cmd_ask(
        interaction: discord.Interaction,
        bot_id: str | None = None,
        message: str | None = None,
    ):
        await interaction.response.defer(ephemeral=not (bot_id and message))
        channel_id = str(interaction.channel_id)
        user = str(interaction.user.id)
        state = get_channel_state(channel_id)

        try:
            targets = await _ask_targets_for_channel(channel_id, state["bot_id"])
        except SlashCommandClientError as exc:
            await interaction.followup.send(f"Error: {exc}")
            return

        if not bot_id or not message:
            await _send_chunks(interaction, format_ask_target_options(targets, command="/ask"))
            return

        target = resolve_ask_target(targets, bot_id)
        if not target:
            await interaction.followup.send(
                f"Unknown bot `{bot_id}` for this channel.\n"
                f"{format_ask_target_options(targets, command='/ask')}"
            )
            return

        client_id = discord_client_id(channel_id)
        # Ingest contract: content = raw text; identity/routing in metadata.
        msg_metadata = {
            "passive": False,
            "source": "discord",
            "sender_type": "human",
            "sender_id": f"discord:{user}",
            "sender_display_name": interaction.user.display_name,
            "channel_external_id": str(channel_id),
            "mention_token": f"<@{user}>",
            "recipient_id": f"bot:{target.bot_id}",
            "trigger_rag": True,
        }
        dispatch_config = {
            "channel_id": channel_id,
            "token": DISCORD_TOKEN,
        }

        try:
            await submit_chat(
                message=message,
                bot_id=target.bot_id,
                client_id=client_id,
                dispatch_type="discord",
                dispatch_config=dispatch_config,
                msg_metadata=msg_metadata,
            )
            await interaction.followup.send(f"Queued request for `{target.bot_id}`.")
        except Exception as e:
            logger.exception("submit_chat failed for Discord /ask in channel %s", channel_id)
            await interaction.followup.send(f"*Error: {str(e)[:500]}*")

    @tree.command(name="context", description="Show context breakdown for current session")
    @app_commands.describe(subcommand="Optional: 'contents' to see actual messages")
    async def cmd_context(interaction: discord.Interaction, subcommand: str | None = None):
        await interaction.response.defer(ephemeral=True)
        channel_id = str(interaction.channel_id)
        state = get_channel_state(channel_id)
        session_id = await _resolve_session_id(channel_id, state["bot_id"])
        if not session_id:
            await interaction.followup.send("No active session for this channel yet. Send a message first.")
            return

        if subcommand == "contents":
            await interaction.followup.send("*Running compression and fetching context contents...*")
            try:
                data = await fetch_session_context_contents(session_id, compress=True)
            except Exception as e:
                await interaction.followup.send(f"Error: {e}")
                return
            compressed = data.get("compressed", False)
            total = data.get("total_messages", 0)
            chars = data.get("total_chars", 0)
            header = f"**Context Contents** \u2014 {total} messages / {chars:,} chars"
            if compressed:
                header += " *(compressed)*"
            lines = [header]
            for i, m in enumerate(data.get("messages", [])):
                role = m.get("role", "?")
                content = m.get("content") or ""
                if isinstance(content, list):
                    content = " ".join(str(p) for p in content)
                if len(content) > 300:
                    content = content[:300] + "\u2026"
                content = content.replace("\n", " \u21b5 ")
                tc = ""
                if m.get("tool_calls"):
                    names = [tc.get("function", {}).get("name", "?") for tc in m["tool_calls"]]
                    tc = f" \u2192 [{', '.join(names)}]"
                tid = ""
                if m.get("tool_call_id"):
                    tid = f" (call_id={m['tool_call_id'][:8]}\u2026)"
                lines.append(f"`[{i}] {role}{tid}:` {content}{tc}")
            text = "\n".join(lines)
            await _send_chunks(interaction, text)
            return

        await _send_backend_command(
            interaction=interaction,
            channel_id=channel_id,
            bot_id=state["bot_id"],
            command_id="context",
        )

    @tree.command(name="compact", description="Compact the current session context")
    async def cmd_compact(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel_id = str(interaction.channel_id)
        state = get_channel_state(channel_id)
        await _send_backend_command(
            interaction=interaction,
            channel_id=channel_id,
            bot_id=state["bot_id"],
            command_id="compact",
        )

    @tree.command(name="todos", description="Show pending todos for the current channel/bot")
    @app_commands.describe(status="'done' to show completed, otherwise shows pending")
    async def cmd_todos(interaction: discord.Interaction, status: str | None = None):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send("`/todos` is retired. Use the channel Todo widget in Spindrel instead.")

    @tree.command(name="health", description="Quick server health check")
    async def cmd_health(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

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
                return "\u26a0\ufe0f timed out"
            except Exception as e:
                return f"\u26a0\ufe0f {e}"

        host_results, server_health = await asyncio.gather(
            asyncio.gather(
                _run("systemctl is-active spindrel spindrel-discord 2>/dev/null || echo 'unknown'"),
                _run("docker ps --format '{{.Names}}\\t{{.Status}}' 2>/dev/null | grep -E 'postgres|searxng|playwright' || echo 'none running'"),
                _run("df -h / | tail -1"),
                _run("tail -1 ~/logs/backup.log 2>/dev/null || echo 'no log'"),
            ),
            fetch_server_health(),
        )
        svc_raw, docker_raw, disk_raw, backup_raw = host_results

        lines: list[str] = ["**Server Status**", ""]

        # Server health (from API)
        srv_icon = "\u2705" if server_health.get("healthy") else "\U0001f6a8"
        lines.append(f"**Agent Server** {srv_icon}")
        if server_health.get("database") is not None:
            db_icon = "\u2705" if server_health["database"] else "\U0001f6a8"
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
            lines.append(f"  \U0001f6a8 {issue}")

        # Host services
        svc_lines = svc_raw.splitlines()
        svc_names = ["spindrel", "spindrel-discord"]
        svc_parts: list[str] = []
        for i, name in enumerate(svc_names):
            status = svc_lines[i].strip() if i < len(svc_lines) else "unknown"
            icon = "\u2705" if status == "active" else "\U0001f6a8"
            svc_parts.append(f"{icon} `{name}`: {status}")
        lines.append("\n**Services**")
        lines.extend(f"  {s}" for s in svc_parts)

        lines.append("\n**Containers**")
        if "none" in docker_raw:
            lines.append("  \U0001f6a8 No matching containers running")
        else:
            for row in docker_raw.splitlines():
                row_parts = row.split("\t", 1)
                name = row_parts[0] if row_parts else row
                st = row_parts[1] if len(row_parts) > 1 else ""
                icon = "\u2705" if "Up" in st else "\U0001f6a8"
                lines.append(f"  {icon} `{name}`: {st}")

        lines.append("\n**Disk**")
        try:
            disk_parts = disk_raw.split()
            use_pct = int(disk_parts[4].rstrip("%")) if len(disk_parts) >= 5 else 0
            icon = "\U0001f6a8" if use_pct > 90 else ("\u26a0\ufe0f" if use_pct > 80 else "\u2705")
            lines.append(f"  {icon} `/`: {disk_parts[4]} used ({disk_parts[3]} avail)")
        except (IndexError, ValueError):
            lines.append(f"  \u26a0\ufe0f `{disk_raw}`")

        lines.append("\n**Last Backup**")
        lines.append(f"  {backup_raw[:200]}")

        await _send_chunks(interaction, "\n".join(lines))

    @tree.command(name="model", description="View or change the model override for this channel")
    @app_commands.describe(arg="Model name, 'clear', or 'list'")
    async def cmd_model(interaction: discord.Interaction, arg: str | None = None):
        await interaction.response.defer(ephemeral=True)
        channel_id = str(interaction.channel_id)
        state = get_channel_state(channel_id)
        bot_id = state["bot_id"]

        if not arg:
            await _send_backend_command(
                interaction=interaction,
                channel_id=channel_id,
                bot_id=bot_id,
                command_id="model",
            )
            return

        if arg.lower() == "list":
            try:
                groups = await list_models()
            except Exception as e:
                await interaction.followup.send(f"Error fetching models: {e}")
                return
            lines = ["**Available Models**"]
            for g in groups:
                provider = g.get("provider_name", "Unknown")
                models = g.get("models", [])
                if not models:
                    continue
                lines.append(f"\n**{provider}**")
                for m in models:
                    lines.append(f"  `{m['id']}`")
            await _send_chunks(interaction, "\n".join(lines))
            return

        await _send_backend_command(
            interaction=interaction,
            channel_id=channel_id,
            bot_id=bot_id,
            command_id="model",
            args=[arg],
        )

    @tree.command(name="audit", description="Set or clear the audit channel for tool call logging")
    @app_commands.describe(arg="Channel mention or ID to log to, or 'off' to disable")
    async def cmd_audit(interaction: discord.Interaction, arg: str | None = None):
        await interaction.response.defer(ephemeral=True)

        if not arg:
            current = get_global_setting("audit_channel")
            if current:
                await interaction.followup.send(f"Audit channel: <#{current}>\nUse `/audit off` to disable.")
            else:
                await interaction.followup.send("No audit channel set.\nUsage: `/audit #channel` or `/audit off`")
            return

        if arg.lower() == "off":
            set_global_setting("audit_channel", None)
            await interaction.followup.send("Audit logging disabled.")
            return

        # Accept <#123456> mention format or raw channel ID
        channel_id = arg.strip()
        if channel_id.startswith("<#") and channel_id.endswith(">"):
            channel_id = channel_id.strip("<#>")

        set_global_setting("audit_channel", channel_id)
        await interaction.followup.send(f"Audit channel set to <#{channel_id}>.\nTool calls across all bots will be logged there.")
