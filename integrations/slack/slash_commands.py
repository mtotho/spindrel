"""Slash commands: /bot, /bots, /ask, /context, /plan, /compact, /todos, /health."""

import asyncio
import logging

from agent_client import (
    compact_session,
    ensure_channel,
    fetch_session_plans,
    fetch_session_context,
    fetch_session_context_compressed,
    fetch_session_context_contents,
    fetch_todos,
    get_channel_session_id,
    list_bots,
    stream_chat,
    update_plan_item_status,
    update_plan_status,
)
from formatting import format_last_active, format_response_for_slack, format_tool_status, split_for_slack
from session_helpers import slack_client_id
from slack_settings import BOT_TOKEN, get_bot_display_info
from state import get_channel_state, set_channel_state

logger = logging.getLogger(__name__)


_ITEM_STATUS_ICON = {
    "pending": "○",
    "in_progress": "◉",
    "done": "✓",
    "skipped": "–",
}


async def _resolve_session_id(channel: str, bot_id: str) -> str | None:
    """Look up the active session_id for a Slack channel from the server."""
    return await get_channel_session_id(channel, bot_id)


def _format_plan(plan: dict, detail: bool = False) -> str:
    items = plan.get("items", [])
    done = sum(1 for i in items if i["status"] == "done")
    total = len(items)
    pid = plan["id"][:8]
    header = f"*[{pid}] {plan['title']}* ({done}/{total} done)"
    if plan["status"] != "active":
        header += f" _{plan['status']}_"
    if not detail:
        return header
    lines = [header]
    if plan.get("description"):
        lines.append(f"  _{plan['description']}_")
    for i, item in enumerate(items, 1):
        icon = _ITEM_STATUS_ICON.get(item["status"], "?")
        lines.append(f"  {icon} {i}. {item['content']}")
        if item.get("notes"):
            lines.append(f"      _{item['notes']}_")
    return "\n".join(lines)


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
        """Route a message to a specific bot: /ask <bot-id> <message>"""
        await ack()
        channel = command.get("channel_id") or ""
        user = command.get("user_id") or "unknown"
        text = (command.get("text") or "").strip()

        if not text:
            bots_list = await list_bots()
            lines = ["Usage: `/ask <bot-id> <message>`", "", "*Available bots:*"]
            lines += [f"  `{b['id']}` — {b['name']}" for b in bots_list]
            await respond("\n".join(lines))
            return

        parts = text.split(None, 1)
        if len(parts) < 2:
            await respond("Usage: `/ask <bot-id> <message>`\nExample: `/ask calculator-bot what is 2+2?`")
            return

        target_bot_id = parts[0].lower()
        message = parts[1].strip()

        if not message:
            await respond("Please provide a message after the bot ID.")
            return

        try:
            bots_list = await list_bots()
            valid = {b["id"] for b in bots_list}
        except Exception:
            valid = set()

        if target_bot_id not in valid:
            await respond(
                f"Unknown bot `{target_bot_id}`.\n"
                f"Available: {', '.join(f'`{b}`' for b in sorted(valid))}"
            )
            return

        client_id = slack_client_id(channel)

        msg_metadata = {
            "passive": False,
            "source": "slack",
            "sender_type": "human",
            "sender_id": f"slack:{user}",
            "recipient_id": f"bot:{target_bot_id}",
            "trigger_rag": True,
        }

        full_message = f"[Slack channel:{channel} user:{user}] {message}"

        dispatch_config = {
            "channel_id": channel,
            "thread_ts": None,
            "token": BOT_TOKEN,
        }

        display_info = get_bot_display_info(target_bot_id)
        identity: dict = {}
        if display_info.get("display_name"):
            identity["username"] = display_info["display_name"]
        if display_info.get("icon_emoji"):
            identity["icon_emoji"] = display_info["icon_emoji"]
        elif display_info.get("icon_url"):
            identity["icon_url"] = display_info["icon_url"]

        thinking_msg = await client.chat_postMessage(
            channel=channel,
            text="⏳ _thinking..._",
            **identity,
        )
        thinking_ts = thinking_msg["ts"]
        thinking_channel = thinking_msg["channel"]

        try:
            client_actions: list = []
            async for event in stream_chat(
                message=full_message,
                bot_id=target_bot_id,
                client_id=client_id,
                dispatch_type="slack",
                dispatch_config=dispatch_config,
                msg_metadata=msg_metadata,
            ):
                etype = event.get("type")
                if etype == "tool_start":
                    tool = event.get("tool", "tool")
                    status = format_tool_status(tool, event.get("args"))
                    await client.chat_update(
                        channel=thinking_channel,
                        ts=thinking_ts,
                        text=status,
                        **identity,
                    )
                elif etype == "queued":
                    try:
                        await client.chat_delete(
                            channel=thinking_channel,
                            ts=thinking_ts,
                        )
                    except Exception:
                        pass
                    return
                elif etype == "response":
                    reply = (event.get("text") or "").strip()
                    client_actions = event.get("client_actions") or []
                    formatted = format_response_for_slack(reply)
                    chunks = split_for_slack(formatted)
                    await client.chat_update(
                        channel=thinking_channel,
                        ts=thinking_ts,
                        text=chunks[0],
                        **identity,
                    )
                    for chunk in chunks[1:]:
                        await client.chat_postMessage(
                            channel=thinking_channel,
                            text=chunk,
                            **identity,
                        )
        except Exception as e:
            await client.chat_update(
                channel=thinking_channel,
                ts=thinking_ts,
                text=f"_Error: {str(e)[:500]}_",
                **identity,
            )

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
            for chunk in split_for_slack(text, max_len=3000):
                await respond(chunk)
            return

        # /context — show breakdown + compressed estimate
        try:
            data = await fetch_session_context(session_id)
        except Exception as e:
            await respond(f"Error fetching context: {e}")
            return

        breakdown = data.get("breakdown")
        if not breakdown:
            await respond("No context breakdown recorded yet for this session.")
            return

        total_chars = data.get("total_chars", 0)
        total_messages = data.get("total_messages", 0)
        iteration = data.get("iteration")

        header = f"*Context Breakdown* — {total_messages} messages / {total_chars:,} chars"
        if iteration:
            header += f" — iter {iteration}"

        rows = sorted(breakdown.items(), key=lambda kv: kv[1].get("chars", 0), reverse=True)
        lines = [header, "```"]
        for role, info in rows:
            chars = info.get("chars", 0)
            pct = (chars / total_chars * 100) if total_chars else 0
            short = role.replace("sys:", "")
            lines.append(f"{short:<22} {chars:>7,}  ({pct:.1f}%)")
        lines.append(f"{'total':<22} {total_chars:>7,}")
        lines.append("```")

        # Fetch compressed estimate (runs the cheap model)
        try:
            comp = await fetch_session_context_compressed(session_id)
            comp_data = comp.get("compressed")
            if comp_data:
                comp_total = comp_data.get("total_chars", 0)
                comp_msgs = comp_data.get("total_messages", 0)
                saved = comp.get("chars_saved", 0)
                pct = comp.get("reduction_pct", 0)
                lines.append("")
                lines.append(f"*Compressed* — {comp_msgs} messages / {comp_total:,} chars "
                             f"(_saves {saved:,} chars · {pct}% reduction_)")
                comp_breakdown = comp_data.get("breakdown", {})
                comp_rows = sorted(comp_breakdown.items(), key=lambda kv: kv[1].get("chars", 0), reverse=True)
                lines.append("```")
                for role, info in comp_rows:
                    chars = info.get("chars", 0)
                    cpct = (chars / comp_total * 100) if comp_total else 0
                    short = role.replace("sys:", "")
                    lines.append(f"{short:<22} {chars:>7,}  ({cpct:.1f}%)")
                lines.append(f"{'total':<22} {comp_total:>7,}")
                lines.append("```")
            else:
                reason = comp.get("reason", "unknown")
                if reason == "below_threshold_or_disabled":
                    lines.append("\n_Compression: skipped (below threshold or disabled)_")
        except Exception as e:
            lines.append(f"\n_Compression estimate failed: {e}_")

        await respond("\n".join(lines))

    @app.command("/plan")
    async def cmd_plan(ack, command, respond):
        await ack()
        channel = command.get("channel_id") or ""
        state = get_channel_state(channel)
        session_id = await _resolve_session_id(channel, state["bot_id"])
        if not session_id:
            await respond("No active session for this channel yet. Send a message first.")
            return
        args = (command.get("text") or "").split()
        sub = args[0].lower() if args else "list"

        # /plan  or  /plan list  or  /plan list all
        if sub in ("list", "ls") or not args:
            fetch_status = "all" if (len(args) > 1 and args[1].lower() == "all") else "active"
            try:
                plans = await fetch_session_plans(session_id, status=fetch_status)
            except Exception as e:
                await respond(f"Error: {e}")
                return
            if not plans:
                label = "No plans" if fetch_status == "active" else "No plans at all"
                await respond(f"{label} for this session.")
                return
            lines = [f"*Plans* ({fetch_status})"]
            for p in plans:
                lines.append(_format_plan(p, detail=False))
            lines.append("\n_Use `/plan <id>` to view details._")
            await respond("\n".join(lines))
            return

        # /plan complete <plan_id_prefix>
        if sub == "complete" and len(args) >= 2:
            prefix = args[1].lower()
            try:
                plans = await fetch_session_plans(session_id, status="active")
            except Exception as e:
                await respond(f"Error: {e}")
                return
            matches = [p for p in plans if p["id"].lower().startswith(prefix)]
            if not matches:
                await respond(f"No active plan starting with `{prefix}`.")
                return
            if len(matches) > 1:
                await respond(f"Ambiguous — {len(matches)} plans match `{prefix}`. Be more specific.")
                return
            plan = matches[0]
            try:
                await update_plan_status(session_id, plan["id"], "complete")
            except Exception as e:
                await respond(f"Error: {e}")
                return
            await respond(f"✓ Plan *{plan['title']}* marked complete.")
            return

        # /plan abandon <plan_id_prefix>
        if sub == "abandon" and len(args) >= 2:
            prefix = args[1].lower()
            try:
                plans = await fetch_session_plans(session_id, status="active")
            except Exception as e:
                await respond(f"Error: {e}")
                return
            matches = [p for p in plans if p["id"].lower().startswith(prefix)]
            if not matches:
                await respond(f"No active plan starting with `{prefix}`.")
                return
            if len(matches) > 1:
                await respond(f"Ambiguous — {len(matches)} plans match `{prefix}`. Be more specific.")
                return
            plan = matches[0]
            try:
                await update_plan_status(session_id, plan["id"], "abandoned")
            except Exception as e:
                await respond(f"Error: {e}")
                return
            await respond(f"Plan *{plan['title']}* abandoned.")
            return

        # /plan done <plan_id_prefix> <item_number>
        # /plan skip <plan_id_prefix> <item_number>
        # /plan pending <plan_id_prefix> <item_number>
        if sub in ("done", "skip", "pending", "progress") and len(args) >= 3:
            status_map = {"done": "done", "skip": "skipped", "pending": "pending", "progress": "in_progress"}
            new_status = status_map[sub]
            prefix = args[1].lower()
            if not args[2].isdigit():
                await respond(f"Usage: `/plan {sub} <plan-id> <item-number>`")
                return
            item_num = int(args[2])
            try:
                plans = await fetch_session_plans(session_id, status="all")
            except Exception as e:
                await respond(f"Error: {e}")
                return
            matches = [p for p in plans if p["id"].lower().startswith(prefix)]
            if not matches:
                await respond(f"No plan starting with `{prefix}`.")
                return
            if len(matches) > 1:
                await respond(f"Ambiguous — {len(matches)} plans match. Be more specific.")
                return
            plan = matches[0]
            if item_num < 1 or item_num > len(plan["items"]):
                await respond(f"Item {item_num} out of range (plan has {len(plan['items'])} items).")
                return
            try:
                await update_plan_item_status(session_id, plan["id"], item_num, new_status)
            except Exception as e:
                await respond(f"Error: {e}")
                return
            item_content = plan["items"][item_num - 1]["content"]
            icon = _ITEM_STATUS_ICON.get(new_status, "?")
            await respond(f"{icon} Item {item_num} marked *{new_status}*: _{item_content}_")
            return

        # /plan <plan_id_prefix>  — show detail
        prefix = sub
        try:
            plans = await fetch_session_plans(session_id, status="all")
        except Exception as e:
            await respond(f"Error: {e}")
            return
        matches = [p for p in plans if p["id"].lower().startswith(prefix)]
        if not matches:
            await respond(
                f"No plan with id starting `{prefix}`.\n"
                "_Usage:_\n"
                "• `/plan` — list active plans\n"
                "• `/plan <id>` — show plan detail\n"
                "• `/plan done <id> <n>` — mark item done\n"
                "• `/plan skip <id> <n>` — mark item skipped\n"
                "• `/plan complete <id>` — complete plan\n"
                "• `/plan abandon <id>` — abandon plan"
            )
            return
        if len(matches) > 1:
            await respond(f"Ambiguous — {len(matches)} plans match `{prefix}`. Be more specific.")
            return
        await respond(_format_plan(matches[0], detail=True))

    @app.command("/compact")
    async def cmd_compact(ack, command, respond):
        await ack()
        channel = command.get("channel_id") or ""
        state = get_channel_state(channel)
        session_id = await _resolve_session_id(channel, state["bot_id"])
        if not session_id:
            await respond("No active session for this channel yet. Send a message first.")
            return
        try:
            result = await compact_session(session_id)
        except Exception as e:
            await respond(f"Error compacting: {e}")
            return
        title = result.get("title") or "(untitled)"
        await respond(f"✓ Compacted. Title: *{title}*")

    @app.command("/todos")
    async def cmd_todos(ack, command, respond):
        """Show pending todos for the current channel/bot. `/todos done` shows completed."""
        await ack()
        channel = command.get("channel_id") or ""
        state = get_channel_state(channel)
        bot_id = state["bot_id"]
        arg = (command.get("text") or "").strip().lower()

        # We need the server-side channel UUID, not the Slack channel ID.
        client_id = slack_client_id(channel)
        ch_data = await ensure_channel(client_id, bot_id)
        if not ch_data or not ch_data.get("id"):
            await respond("No channel registered yet. Send a message first.")
            return
        channel_uuid = ch_data["id"]

        status = "done" if arg == "done" else "pending"
        try:
            todos = await fetch_todos(bot_id, channel_uuid, status=status)
        except Exception as e:
            await respond(f"Error fetching todos: {e}")
            return

        if not todos:
            label = "completed" if status == "done" else "pending"
            await respond(f"No {label} todos for `{bot_id}` in this channel.")
            return

        # Group by priority (descending).
        groups: dict[int, list[dict]] = {}
        for t in todos:
            p = t.get("priority", 0)
            groups.setdefault(p, []).append(t)

        lines: list[str] = []
        heading = "Recently Completed" if status == "done" else "Pending Todos"
        lines.append(f"*{heading}* — `{bot_id}`")

        for priority in sorted(groups.keys(), reverse=True):
            if priority > 0:
                lines.append(f"\n*Priority {priority}*")
            elif len(groups) > 1:
                lines.append("\n*Normal*")
            for t in groups[priority]:
                icon = "✓" if t["status"] == "done" else "○"
                lines.append(f"  {icon} {t['content']}")

        await respond("\n".join(lines))

    @app.command("/health")
    async def cmd_status(ack, command, respond):
        """Quick server health check — runs host commands directly, no bot interaction."""
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

        # Run all checks concurrently.
        results = await asyncio.gather(
            _run("systemctl is-active thoth thoth-slack 2>/dev/null || echo 'unknown'"),
            _run("docker ps --format '{{.Names}}\\t{{.Status}}' 2>/dev/null | grep -E 'postgres|searxng|playwright' || echo 'none running'"),
            _run("df -h / | tail -1"),
            _run("tail -1 ~/logs/backup.log 2>/dev/null || echo 'no log'"),
            _run("git -C /home/thothbot/agent-server log --oneline -1 2>/dev/null || echo 'unknown'"),
        )
        svc_raw, docker_raw, disk_raw, backup_raw, git_raw = results

        lines: list[str] = ["*Server Status*", ""]

        # Services
        svc_lines = svc_raw.splitlines()
        svc_names = ["thoth", "thoth-slack"]
        svc_parts: list[str] = []
        for i, name in enumerate(svc_names):
            status = svc_lines[i].strip() if i < len(svc_lines) else "unknown"
            icon = "✅" if status == "active" else "🚨"
            svc_parts.append(f"{icon} `{name}`: {status}")
        lines.append("*Services*")
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

        # Git
        lines.append("\n*Deploy*")
        lines.append(f"  `{git_raw[:120]}`")

        await respond("\n".join(lines))
