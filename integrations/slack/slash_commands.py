"""Slash commands: /bot, /bots, /ask, /context, /plan, /compact."""

from agent_client import (
    compact_session,
    ensure_channel,
    fetch_session_plans,
    fetch_session_context,
    list_bots,
    stream_chat,
    update_plan_item_status,
    update_plan_status,
)
from formatting import format_last_active, format_response_for_slack
from session_helpers import derive_session_id, slack_client_id
from slack_settings import BOT_TOKEN, get_bot_display_info
from state import get_channel_state, set_channel_state


_ITEM_STATUS_ICON = {
    "pending": "○",
    "in_progress": "◉",
    "done": "✓",
    "skipped": "–",
}


def _resolve_session_id(channel: str) -> str:
    client_id = slack_client_id(channel)
    return derive_session_id(client_id)


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
                    await client.chat_update(
                        channel=thinking_channel,
                        ts=thinking_ts,
                        text=f"🔧 _{tool}..._",
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
                    await client.chat_update(
                        channel=thinking_channel,
                        ts=thinking_ts,
                        text=format_response_for_slack(reply),
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
        channel = command.get("channel_id") or ""
        session_id = _resolve_session_id(channel)
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
        await respond("\n".join(lines))

    @app.command("/plan")
    async def cmd_plan(ack, command, respond):
        await ack()
        channel = command.get("channel_id") or ""
        session_id = _resolve_session_id(channel)
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
        session_id = _resolve_session_id(channel)
        try:
            result = await compact_session(session_id)
        except Exception as e:
            await respond(f"Error compacting: {e}")
            return
        title = result.get("title") or "(untitled)"
        await respond(f"✓ Compacted. Title: *{title}*")
