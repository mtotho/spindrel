"""Discord application commands: /bot, /bots, /ask, /context, /compact, /plan, /model, /health, /audit."""
import asyncio
import logging

import discord
from discord import app_commands

from agent_client import (
    compact_session,
    ensure_channel,
    fetch_server_health,
    fetch_session_plans,
    fetch_session_context,
    fetch_session_context_compressed,
    fetch_session_context_contents,
    fetch_session_context_diagnostics,
    fetch_todos,
    get_channel_session_id,
    get_channel_settings,
    list_bots,
    list_models,
    stream_chat,
    update_channel_settings,
    update_plan_item_status,
    update_plan_status,
)
from formatting import format_last_active, format_response_for_discord, format_tool_status, split_for_discord
from session_helpers import discord_client_id
from discord_settings import DISCORD_TOKEN, get_bot_display_info
from state import get_channel_state, get_global_setting, set_channel_state, set_global_setting

logger = logging.getLogger(__name__)

_ITEM_STATUS_ICON = {
    "pending": "\u25cb",
    "in_progress": "\u25c9",
    "done": "\u2713",
    "skipped": "\u2013",
}


async def _resolve_session_id(channel_id: str, bot_id: str) -> str | None:
    """Look up the active session_id for a Discord channel from the server."""
    return await get_channel_session_id(channel_id, bot_id)


def _format_plan(plan: dict, detail: bool = False) -> str:
    items = plan.get("items", [])
    done = sum(1 for i in items if i["status"] == "done")
    total = len(items)
    pid = plan["id"][:8]
    header = f"**[{pid}] {plan['title']}** ({done}/{total} done)"
    if plan["status"] != "active":
        header += f" *{plan['status']}*"
    if not detail:
        return header
    lines = [header]
    if plan.get("description"):
        lines.append(f"  *{plan['description']}*")
    for i, item in enumerate(items, 1):
        icon = _ITEM_STATUS_ICON.get(item["status"], "?")
        lines.append(f"  {icon} {i}. {item['content']}")
        if item.get("notes"):
            lines.append(f"      *{item['notes']}*")
    return "\n".join(lines)


async def _send_chunks(interaction: discord.Interaction, text: str) -> None:
    """Send a potentially long response, splitting for Discord's 2000 char limit."""
    chunks = split_for_discord(text)
    if not chunks:
        return
    await interaction.followup.send(chunks[0])
    for chunk in chunks[1:]:
        await interaction.followup.send(chunk)


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
    @app_commands.describe(bot_id="Target bot ID", message="Message to send")
    async def cmd_ask(interaction: discord.Interaction, bot_id: str, message: str):
        await interaction.response.defer()
        channel_id = str(interaction.channel_id)
        user = str(interaction.user.id)

        try:
            bots_list = await list_bots()
            valid = {b["id"] for b in bots_list}
        except Exception:
            valid = set()

        if bot_id not in valid:
            await interaction.followup.send(
                f"Unknown bot `{bot_id}`.\n"
                f"Available: {', '.join(f'`{b}`' for b in sorted(valid))}"
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
            "recipient_id": f"bot:{bot_id}",
            "trigger_rag": True,
        }
        full_message = message
        dispatch_config = {
            "channel_id": channel_id,
            "token": DISCORD_TOKEN,
        }

        thinking_msg = await interaction.followup.send("\u23f3 *thinking...*", wait=True)

        try:
            async for event in stream_chat(
                message=full_message,
                bot_id=bot_id,
                client_id=client_id,
                dispatch_type="discord",
                dispatch_config=dispatch_config,
                msg_metadata=msg_metadata,
            ):
                etype = event.get("type")
                if etype == "tool_start":
                    tool = event.get("tool", "tool")
                    status = format_tool_status(tool, event.get("args"))
                    await thinking_msg.edit(content=status)
                elif etype == "queued":
                    try:
                        await thinking_msg.delete()
                    except Exception:
                        pass
                    return
                elif etype == "response":
                    reply = (event.get("text") or "").strip()
                    formatted = format_response_for_discord(reply)
                    chunks = split_for_discord(formatted)
                    await thinking_msg.edit(content=chunks[0])
                    for chunk in chunks[1:]:
                        await interaction.followup.send(chunk)
        except Exception as e:
            await thinking_msg.edit(content=f"*Error: {str(e)[:500]}*")

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

        # Default: show breakdown
        try:
            data = await fetch_session_context(session_id)
        except Exception as e:
            await interaction.followup.send(f"Error fetching context: {e}")
            return

        breakdown = data.get("breakdown")
        if not breakdown:
            await interaction.followup.send("No context breakdown recorded yet for this session.")
            return

        total_chars = data.get("total_chars", 0)
        total_messages = data.get("total_messages", 0)
        iteration = data.get("iteration")

        comp_info = data.get("compression")
        if comp_info:
            orig_msgs = comp_info.get("original_messages", "?")
            orig_chars = comp_info.get("original_chars", 0)
            comp_chars = comp_info.get("compressed_chars", 0)
            saved_pct = round((1 - comp_chars / orig_chars) * 100, 1) if orig_chars else 0
            header = (f"**Last LLM Call** \u2014 {orig_msgs} msgs \u2192 **{total_messages} msgs** "
                      f"({orig_chars:,} \u2192 {total_chars:,} chars, {saved_pct}% compressed)")
        else:
            header = f"**Last LLM Call** \u2014 {total_messages} messages / {total_chars:,} chars"
        if iteration:
            header += f" \u2014 iter {iteration}"

        rows = sorted(breakdown.items(), key=lambda kv: kv[1].get("chars", 0), reverse=True)
        lines = [header, "```"]
        for role, info in rows:
            chars = info.get("chars", 0)
            pct = (chars / total_chars * 100) if total_chars else 0
            short = role.replace("sys:", "")
            lines.append(f"{short:<22} {chars:>7,}  ({pct:.1f}%)")
        lines.append(f"{'total':<22} {total_chars:>7,}")
        lines.append("```")

        await _send_chunks(interaction, "\n".join(lines))

    @tree.command(name="plan", description="View and manage plans")
    @app_commands.describe(args="Subcommand: list, <id>, done <id> <n>, complete <id>, abandon <id>")
    async def cmd_plan(interaction: discord.Interaction, args: str | None = None):
        await interaction.response.defer(ephemeral=True)
        channel_id = str(interaction.channel_id)
        state = get_channel_state(channel_id)
        session_id = await _resolve_session_id(channel_id, state["bot_id"])
        if not session_id:
            await interaction.followup.send("No active session for this channel yet. Send a message first.")
            return

        parts = (args or "").split()
        sub = parts[0].lower() if parts else "list"

        if sub in ("list", "ls") or not parts:
            fetch_status = "all" if (len(parts) > 1 and parts[1].lower() == "all") else "active"
            try:
                plans = await fetch_session_plans(session_id, status=fetch_status)
            except Exception as e:
                await interaction.followup.send(f"Error: {e}")
                return
            if not plans:
                label = "No plans" if fetch_status == "active" else "No plans at all"
                await interaction.followup.send(f"{label} for this session.")
                return
            lines = [f"**Plans** ({fetch_status})"]
            for p in plans:
                lines.append(_format_plan(p, detail=False))
            lines.append("\n*Use `/plan <id>` to view details.*")
            await _send_chunks(interaction, "\n".join(lines))
            return

        if sub == "complete" and len(parts) >= 2:
            prefix = parts[1].lower()
            try:
                plans = await fetch_session_plans(session_id, status="active")
            except Exception as e:
                await interaction.followup.send(f"Error: {e}")
                return
            matches = [p for p in plans if p["id"].lower().startswith(prefix)]
            if not matches:
                await interaction.followup.send(f"No active plan starting with `{prefix}`.")
                return
            if len(matches) > 1:
                await interaction.followup.send(f"Ambiguous \u2014 {len(matches)} plans match `{prefix}`. Be more specific.")
                return
            plan = matches[0]
            try:
                await update_plan_status(session_id, plan["id"], "complete")
            except Exception as e:
                await interaction.followup.send(f"Error: {e}")
                return
            await interaction.followup.send(f"\u2713 Plan **{plan['title']}** marked complete.")
            return

        if sub == "abandon" and len(parts) >= 2:
            prefix = parts[1].lower()
            try:
                plans = await fetch_session_plans(session_id, status="active")
            except Exception as e:
                await interaction.followup.send(f"Error: {e}")
                return
            matches = [p for p in plans if p["id"].lower().startswith(prefix)]
            if not matches:
                await interaction.followup.send(f"No active plan starting with `{prefix}`.")
                return
            if len(matches) > 1:
                await interaction.followup.send(f"Ambiguous \u2014 {len(matches)} plans match `{prefix}`. Be more specific.")
                return
            plan = matches[0]
            try:
                await update_plan_status(session_id, plan["id"], "abandoned")
            except Exception as e:
                await interaction.followup.send(f"Error: {e}")
                return
            await interaction.followup.send(f"Plan **{plan['title']}** abandoned.")
            return

        if sub in ("done", "skip", "pending", "progress") and len(parts) >= 3:
            status_map = {"done": "done", "skip": "skipped", "pending": "pending", "progress": "in_progress"}
            new_status = status_map[sub]
            prefix = parts[1].lower()
            if not parts[2].isdigit():
                await interaction.followup.send(f"Usage: `/plan {sub} <plan-id> <item-number>`")
                return
            item_num = int(parts[2])
            try:
                plans = await fetch_session_plans(session_id, status="all")
            except Exception as e:
                await interaction.followup.send(f"Error: {e}")
                return
            matches = [p for p in plans if p["id"].lower().startswith(prefix)]
            if not matches:
                await interaction.followup.send(f"No plan starting with `{prefix}`.")
                return
            if len(matches) > 1:
                await interaction.followup.send(f"Ambiguous \u2014 {len(matches)} plans match. Be more specific.")
                return
            plan = matches[0]
            if item_num < 1 or item_num > len(plan["items"]):
                await interaction.followup.send(f"Item {item_num} out of range (plan has {len(plan['items'])} items).")
                return
            try:
                await update_plan_item_status(session_id, plan["id"], item_num, new_status)
            except Exception as e:
                await interaction.followup.send(f"Error: {e}")
                return
            item_content = plan["items"][item_num - 1]["content"]
            icon = _ITEM_STATUS_ICON.get(new_status, "?")
            await interaction.followup.send(f"{icon} Item {item_num} marked **{new_status}**: *{item_content}*")
            return

        # /plan <plan_id_prefix> -- show detail
        prefix = sub
        try:
            plans = await fetch_session_plans(session_id, status="all")
        except Exception as e:
            await interaction.followup.send(f"Error: {e}")
            return
        matches = [p for p in plans if p["id"].lower().startswith(prefix)]
        if not matches:
            await interaction.followup.send(
                f"No plan with id starting `{prefix}`.\n"
                "*Usage:*\n"
                "\u2022 `/plan` \u2014 list active plans\n"
                "\u2022 `/plan <id>` \u2014 show plan detail\n"
                "\u2022 `/plan done <id> <n>` \u2014 mark item done\n"
                "\u2022 `/plan skip <id> <n>` \u2014 mark item skipped\n"
                "\u2022 `/plan complete <id>` \u2014 complete plan\n"
                "\u2022 `/plan abandon <id>` \u2014 abandon plan"
            )
            return
        if len(matches) > 1:
            await interaction.followup.send(f"Ambiguous \u2014 {len(matches)} plans match `{prefix}`. Be more specific.")
            return
        await _send_chunks(interaction, _format_plan(matches[0], detail=True))

    @tree.command(name="compact", description="Compact the current session context")
    async def cmd_compact(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel_id = str(interaction.channel_id)
        state = get_channel_state(channel_id)
        session_id = await _resolve_session_id(channel_id, state["bot_id"])
        if not session_id:
            await interaction.followup.send("No active session for this channel yet. Send a message first.")
            return
        try:
            result = await compact_session(session_id)
        except Exception as e:
            await interaction.followup.send(f"Error compacting: {e}")
            return
        title = result.get("title") or "(untitled)"
        await interaction.followup.send(f"\u2713 Compacted. Title: **{title}**")

    @tree.command(name="todos", description="Show pending todos for the current channel/bot")
    @app_commands.describe(status="'done' to show completed, otherwise shows pending")
    async def cmd_todos(interaction: discord.Interaction, status: str | None = None):
        await interaction.response.defer(ephemeral=True)
        channel_id = str(interaction.channel_id)
        state = get_channel_state(channel_id)
        bot_id = state["bot_id"]

        client_id = discord_client_id(channel_id)
        ch_data = await ensure_channel(client_id, bot_id)
        if not ch_data or not ch_data.get("id"):
            await interaction.followup.send("No channel registered yet. Send a message first.")
            return
        channel_uuid = ch_data["id"]

        fetch_status = "done" if status and status.lower() == "done" else "pending"
        try:
            todos = await fetch_todos(bot_id, channel_uuid, status=fetch_status)
        except Exception as e:
            await interaction.followup.send(f"Error fetching todos: {e}")
            return

        if not todos:
            label = "completed" if fetch_status == "done" else "pending"
            await interaction.followup.send(f"No {label} todos for `{bot_id}` in this channel.")
            return

        groups: dict[int, list[dict]] = {}
        for t in todos:
            p = t.get("priority", 0)
            groups.setdefault(p, []).append(t)

        lines: list[str] = []
        heading = "Recently Completed" if fetch_status == "done" else "Pending Todos"
        lines.append(f"**{heading}** \u2014 `{bot_id}`")

        for priority in sorted(groups.keys(), reverse=True):
            if priority > 0:
                lines.append(f"\n**Priority {priority}**")
            elif len(groups) > 1:
                lines.append("\n**Normal**")
            for t in groups[priority]:
                icon = "\u2713" if t["status"] == "done" else "\u25cb"
                lines.append(f"  {icon} {t['content']}")

        await _send_chunks(interaction, "\n".join(lines))

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

        client_id = discord_client_id(channel_id)
        ch_data = await ensure_channel(client_id, bot_id)
        if not ch_data or not ch_data.get("id"):
            await interaction.followup.send("No channel registered yet. Send a message first.")
            return
        channel_uuid = ch_data["id"]

        if not arg:
            try:
                settings = await get_channel_settings(channel_uuid)
            except Exception as e:
                await interaction.followup.send(f"Error: {e}")
                return
            override = settings.get("model_override")
            if override:
                await interaction.followup.send(f"**Model override:** `{override}`\n*Bot default: `{bot_id}`*\nUse `/model clear` to revert.")
            else:
                bots_list = await list_bots()
                bot_model = next((b.get("model", "?") for b in bots_list if b["id"] == bot_id), "?")
                await interaction.followup.send(f"**No model override set.**\nUsing bot default: `{bot_model}`\nUse `/model <model-name>` to override.")
            return

        if arg.lower() == "clear":
            try:
                await update_channel_settings(channel_uuid, {"model_override": None, "model_provider_id_override": None})
            except Exception as e:
                await interaction.followup.send(f"Error: {e}")
                return
            await interaction.followup.send("Model override cleared. Using bot default.")
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

        # Set override (fuzzy match)
        target = arg.lower()
        try:
            groups = await list_models()
        except Exception as e:
            await interaction.followup.send(f"Error: {e}")
            return

        all_models = []
        for g in groups:
            for m in g.get("models", []):
                all_models.append(m["id"])

        match = None
        for mid in all_models:
            if mid.lower() == target:
                match = mid
                break

        if not match:
            candidates = [mid for mid in all_models if target in mid.lower()]
            if len(candidates) == 1:
                match = candidates[0]
            elif len(candidates) > 1:
                top = candidates[:10]
                await interaction.followup.send(
                    f"Ambiguous \u2014 {len(candidates)} models match `{arg}`:\n"
                    + "\n".join(f"  `{c}`" for c in top)
                    + ("\n  ..." if len(candidates) > 10 else "")
                )
                return

        if not match:
            await interaction.followup.send(f"No model matching `{arg}`. Use `/model list` to see available models.")
            return

        try:
            await update_channel_settings(channel_uuid, {"model_override": match})
        except Exception as e:
            await interaction.followup.send(f"Error: {e}")
            return
        await interaction.followup.send(f"Model override set to `{match}`.\nUse `/model clear` to revert to bot default.")

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
