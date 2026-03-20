"""Slash commands: /bot, /sessions, /session, /bots, /context, /plan."""
import uuid

from agent_client import (
    compact_session,
    fetch_session_context,
    fetch_session_plans,
    fetch_sessions,
    list_bots,
    update_plan_item_status,
    update_plan_status,
)
from formatting import format_last_active
from session_helpers import fuzzy_find_session, slack_client_id
from state import get_channel_state, set_channel_state


_ITEM_STATUS_ICON = {
    "pending": "○",
    "in_progress": "◉",
    "done": "✓",
    "skipped": "–",
}


def _resolve_session_id(channel: str) -> str:
    state = get_channel_state(channel)
    client_id = slack_client_id(channel)
    return state.get("session_id") or str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{client_id}:{state['bot_id']}"))


def _format_plan(plan: dict, detail: bool = False) -> str:
    items = plan.get("items", [])
    done = sum(1 for i in items if i["status"] == "done")
    skipped = sum(1 for i in items if i["status"] == "skipped")
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
            await respond(f"Current bot: `{state['bot_id']}`")
            return

        valid = {b["id"] for b in await list_bots()}

        if arg not in valid:
            await respond(f"Unknown bot. Available: {', '.join(sorted(valid))}")
            return

        set_channel_state(channel, bot_id=arg, session_id=None)
        await respond(f"Switched to `{arg}`. New session for this bot.")

    @app.command("/sessions")
    async def cmd_sessions(ack, command, respond):
        await ack()
        channel = command.get("channel_id") or ""
        state = get_channel_state(channel)
        client_id = slack_client_id(channel)
        bot_id = state["bot_id"]

        current_sid = (
            state.get("session_id") or str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{client_id}:{bot_id}"))
        ).lower()

        try:
            sessions = await fetch_sessions(channel)
        except Exception as e:
            await respond(f"Error listing sessions: {e}")
            return

        if not sessions:
            await respond("No sessions. Send a message to create one, or `/session new`.")
            return

        lines = []
        for i, s in enumerate(sessions[:25], 1):
            sid = s.get("id") or ""
            selected = sid.lower() == current_sid if sid else False
            marker = "[*] " if selected else "    "
            title = (s.get("title") or "(untitled)")[:28]
            last = format_last_active(s.get("last_active") or "")
            line = f"{marker}{i}. `{sid[:8]}` {title} bot=`{s.get('bot_id', '')}` {last}"
            lines.append(line)
        if len(sessions) > 25:
            lines.append(f"_... and {len(sessions) - 25} more_")
        lines.append("")
        lines.append("_Select: /session <number or id or title>_")
        await respond("\n".join(lines))

    @app.command("/session")
    async def cmd_session(ack, command, respond):
        await ack()
        channel = command.get("channel_id") or ""
        arg = (command.get("text") or "").strip()

        state = get_channel_state(channel)
        client_id = slack_client_id(channel)
        default_sid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{client_id}:{state['bot_id']}"))

        if not arg:
            sid = state.get("session_id") or default_sid
            await respond(f"Current session: `{sid[:8]}...`")
            return

        if arg.lower() == "new":
            set_channel_state(channel, session_id=str(uuid.uuid4()))
            await respond("Started a new session.")
            return

        try:
            sessions = await fetch_sessions(channel)
        except Exception as e:
            await respond(f"Error: {e}")
            return

        if arg.isdigit():
            index = int(arg) - 1
            if 0 <= index < len(sessions):
                sid = sessions[index]["id"]
                set_channel_state(channel, session_id=sid)
                title = sessions[index].get("title") or "(untitled)"
                await respond(f"✓ Switched to session `{sid[:8]}...` {title}")
            else:
                await respond("Invalid session number. Use `/sessions` to list.")
            return

        try:
            sid_parsed = str(uuid.UUID(arg))
            found = any((s.get("id") or "").lower() == sid_parsed.lower() for s in sessions)
            if found:
                set_channel_state(channel, session_id=sid_parsed)
                await respond(f"Switched to session `{sid_parsed[:8]}...`")
            else:
                await respond("Session with that UUID not found for this client.")
            return
        except ValueError:
            pass

        found = fuzzy_find_session(sessions, arg)
        if found:
            sid = found["id"]
            set_channel_state(channel, session_id=sid)
            title = found.get("title") or "(untitled)"
            await respond(f"Switched to session `{sid[:8]}...` ({title})")
        else:
            await respond("No session found matching that number, id, or title. Use `/sessions` to list.")

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
