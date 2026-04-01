"""Mission Control service layer — shared operations for tools + API router.

Both the MC bot tools and the MC API router delegate here for the
read-parse-mutate-serialize-write cycle on workspace markdown files.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bot resolution
# ---------------------------------------------------------------------------

async def _resolve_bot(channel_id: str):
    """Resolve the bot config for a channel. Falls back to first available bot."""
    import uuid as _uuid
    from app.agent.bots import get_bot, list_bots
    try:
        from app.db.engine import async_session
        from app.db.models import Channel
        async with async_session() as db:
            ch = await db.get(Channel, _uuid.UUID(channel_id))
            if ch:
                return get_bot(ch.bot_id)
    except Exception:
        logger.warning("Could not resolve bot for channel %s, falling back", channel_id, exc_info=True)
    try:
        return get_bot("default")
    except Exception:
        bots = list_bots()
        if bots:
            return bots[0]
        raise ValueError("No bots configured — cannot resolve workspace path")


def _get_bot(bot_id: str):
    """Get a bot by ID (sync, for router endpoints that already have bot_id)."""
    from app.agent.bots import get_bot
    return get_bot(bot_id)


# ---------------------------------------------------------------------------
# Workspace I/O helpers
# ---------------------------------------------------------------------------

async def _read_tasks_md(channel_id: str) -> tuple[str, list[dict]]:
    """Read and parse tasks.md for a channel. Creates default if missing."""
    from app.services.channel_workspace import read_workspace_file
    from app.services.task_board import parse_tasks_md, serialize_tasks_md, default_columns

    bot = await _resolve_bot(channel_id)
    content = await asyncio.to_thread(read_workspace_file, channel_id, bot, "tasks.md")
    if content:
        return content, parse_tasks_md(content)

    columns = default_columns()
    return serialize_tasks_md(columns), columns


async def _write_tasks_md(channel_id: str, columns: list[dict]) -> str:
    """Serialize and write tasks.md for a channel."""
    from app.services.channel_workspace import ensure_channel_workspace, write_workspace_file
    from app.services.task_board import serialize_tasks_md

    bot = await _resolve_bot(channel_id)
    await asyncio.to_thread(ensure_channel_workspace, channel_id, bot)
    content = serialize_tasks_md(columns)
    await asyncio.to_thread(write_workspace_file, channel_id, bot, "tasks.md", content)
    return content


async def _read_plans_md(channel_id: str) -> tuple[str, list[dict]]:
    """Read and parse plans.md for a channel."""
    from app.services.channel_workspace import read_workspace_file
    from app.services.plan_board import parse_plans_md

    bot = await _resolve_bot(channel_id)
    content = await asyncio.to_thread(read_workspace_file, channel_id, bot, "plans.md")
    if content:
        return content, parse_plans_md(content)
    return "", []


async def _write_plans_md(channel_id: str, plans: list[dict]) -> str:
    """Serialize and write plans.md for a channel."""
    from app.services.channel_workspace import ensure_channel_workspace, write_workspace_file
    from app.services.plan_board import serialize_plans_md

    bot = await _resolve_bot(channel_id)
    await asyncio.to_thread(ensure_channel_workspace, channel_id, bot)
    content = serialize_plans_md(plans)
    await asyncio.to_thread(write_workspace_file, channel_id, bot, "plans.md", content)
    return content


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------

async def append_timeline(channel_id: str, event: str) -> None:
    """Append an event line to the channel's timeline.md.

    Format: entries grouped under ``## YYYY-MM-DD`` date headers,
    newest day first, newest event at the top of its day section.
    """
    from app.services.channel_workspace import (
        ensure_channel_workspace,
        read_workspace_file,
        write_workspace_file,
    )

    bot = await _resolve_bot(channel_id)
    await asyncio.to_thread(ensure_channel_workspace, channel_id, bot)

    now = datetime.now(timezone.utc).astimezone()
    today_header = f"## {now.strftime('%Y-%m-%d')}"
    time_str = now.strftime("%H:%M")
    entry_line = f"- {time_str} — {event}"

    content = await asyncio.to_thread(read_workspace_file, channel_id, bot, "timeline.md") or ""

    if today_header in content:
        content = content.replace(today_header, f"{today_header}\n{entry_line}", 1)
    else:
        new_section = f"{today_header}\n{entry_line}\n"
        content = f"{new_section}\n{content}" if content.strip() else new_section

    await asyncio.to_thread(write_workspace_file, channel_id, bot, "timeline.md", content)


def parse_timeline_md(content: str) -> list[dict]:
    """Parse timeline.md into structured event dicts.

    Returns list of ``{"date": "YYYY-MM-DD", "time": "HH:MM", "event": "..."}``
    in file order (newest first).
    """
    events: list[dict] = []
    current_date: str | None = None
    date_re = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})")
    entry_re = re.compile(r"^-\s+(\d{1,2}:\d{2})\s*[—–-]\s*(.+)")

    for line in content.splitlines():
        line = line.strip()
        dm = date_re.match(line)
        if dm:
            current_date = dm.group(1)
            continue
        em = entry_re.match(line)
        if em and current_date:
            events.append({
                "date": current_date,
                "time": em.group(1),
                "event": em.group(2).strip(),
            })
    return events


# ---------------------------------------------------------------------------
# Task card operations (shared by tools + router)
# ---------------------------------------------------------------------------

async def create_card(
    channel_id: str,
    title: str,
    column: str = "Backlog",
    priority: str = "medium",
    assigned: str = "",
    tags: str = "",
    due: str = "",
    description: str = "",
) -> dict:
    """Create a new task card. Returns {"card": dict, "column": str, "card_id": str}."""
    from app.services.task_board import generate_card_id

    _raw, columns = await _read_tasks_md(channel_id)

    target_col = None
    for col in columns:
        if col["name"].lower() == column.lower():
            target_col = col
            break

    if target_col is None:
        target_col = {"name": column, "cards": []}
        done_idx = next((i for i, c in enumerate(columns) if c["name"].lower() == "done"), None)
        if done_idx is not None:
            columns.insert(done_idx, target_col)
        else:
            columns.append(target_col)

    card_id = generate_card_id()
    meta: dict[str, str] = {"id": card_id}
    if assigned:
        meta["assigned"] = assigned
    meta["priority"] = priority
    meta["created"] = date.today().isoformat()
    if tags:
        meta["tags"] = tags
    if due:
        meta["due"] = due

    card = {"title": title, "meta": meta, "description": description}
    target_col["cards"].append(card)

    await _write_tasks_md(channel_id, columns)

    # Auto-log to timeline
    try:
        await append_timeline(
            channel_id,
            f"New card created: {card_id} \"{title}\" in **{target_col['name']}**",
        )
    except Exception:
        logger.debug("Failed to log timeline event for create_card", exc_info=True)

    return {"card": card, "column": target_col["name"], "card_id": card_id}


async def move_card(
    channel_id: str,
    card_id: str,
    to_column: str,
    from_column: str | None = None,
) -> dict:
    """Move a card between columns. Returns {"card": dict, "from_column": str, "to_column": str}.

    If from_column is provided, validates the card is in that column (raises ValueError on mismatch).
    If card not found, raises ValueError.
    """
    _raw, columns = await _read_tasks_md(channel_id)

    found_card = None
    source_col_name = None
    for col in columns:
        for i, card in enumerate(col["cards"]):
            if card["meta"].get("id") == card_id:
                if from_column and col["name"].lower() != from_column.lower():
                    raise ValueError(
                        f"Card {card_id} is in '{col['name']}', not '{from_column}'"
                    )
                found_card = col["cards"].pop(i)
                source_col_name = col["name"]
                break
        if found_card:
            break

    if not found_card:
        raise ValueError(f"Card {card_id} not found")

    target_col = None
    for col in columns:
        if col["name"].lower() == to_column.lower():
            target_col = col
            break

    if target_col is None:
        target_col = {"name": to_column, "cards": []}
        columns.append(target_col)

    # Add transition metadata
    today = date.today().isoformat()
    if to_column.lower() == "in progress":
        found_card["meta"]["started"] = today
    elif to_column.lower() == "done":
        found_card["meta"]["completed"] = today

    target_col["cards"].append(found_card)
    await _write_tasks_md(channel_id, columns)

    # Auto-log to timeline
    try:
        await append_timeline(
            channel_id,
            f"Card {card_id} moved to **{target_col['name']}** (was: {source_col_name}) — \"{found_card['title']}\"",
        )
    except Exception:
        logger.debug("Failed to log timeline event for move_card", exc_info=True)

    return {"card": found_card, "from_column": source_col_name, "to_column": target_col["name"]}


async def update_card(
    channel_id: str,
    card_id: str,
    title: str | None = None,
    description: str | None = None,
    priority: str | None = None,
    assigned: str | None = None,
    due: str | None = None,
    tags: str | None = None,
) -> dict:
    """Update card fields. Returns {"card": dict, "changes": list[str]}.

    Raises ValueError if card not found.
    """
    _raw, columns = await _read_tasks_md(channel_id)

    found_card = None
    for col in columns:
        for card in col["cards"]:
            if card["meta"].get("id") == card_id:
                found_card = card
                break
        if found_card:
            break

    if not found_card:
        raise ValueError(f"Card {card_id} not found")

    changes: list[str] = []
    if title is not None and title != found_card["title"]:
        found_card["title"] = title
        changes.append("title")
    if description is not None and description != found_card.get("description", ""):
        found_card["description"] = description
        changes.append("description")
    if priority is not None and priority != found_card["meta"].get("priority", ""):
        found_card["meta"]["priority"] = priority
        changes.append("priority")
    if assigned is not None:
        if assigned:
            found_card["meta"]["assigned"] = assigned
        else:
            found_card["meta"].pop("assigned", None)
        changes.append("assigned")
    if due is not None:
        if due:
            found_card["meta"]["due"] = due
        else:
            found_card["meta"].pop("due", None)
        changes.append("due")
    if tags is not None:
        if tags:
            found_card["meta"]["tags"] = tags
        else:
            found_card["meta"].pop("tags", None)
        changes.append("tags")

    if changes:
        await _write_tasks_md(channel_id, columns)
        try:
            change_str = ", ".join(changes)
            await append_timeline(
                channel_id,
                f"Card {card_id} updated ({change_str}) — \"{found_card['title']}\"",
            )
        except Exception:
            logger.debug("Failed to log timeline event for update_card", exc_info=True)

    return {"card": found_card, "changes": changes}


# ---------------------------------------------------------------------------
# Plan operations (shared by tools + router)
# ---------------------------------------------------------------------------

async def approve_plan(channel_id: str, plan_id: str) -> dict:
    """Approve a draft plan → approved. Returns {"plan": dict, "plans_list": list}.

    Raises ValueError if plan not found or not in draft status.
    """
    _raw, plans_list = await _read_plans_md(channel_id)

    plan = None
    for p in plans_list:
        if p["meta"].get("id") == plan_id:
            plan = p
            break

    if not plan:
        raise ValueError(f"Plan '{plan_id}' not found")
    if plan["status"] != "draft":
        raise ValueError(f"Plan is [{plan['status']}], expected [draft]")

    plan["status"] = "approved"
    plan["meta"]["approved"] = date.today().isoformat()

    await _write_plans_md(channel_id, plans_list)

    try:
        await append_timeline(channel_id, f"Plan approved: **{plan['title']}** ({plan_id})")
    except Exception:
        logger.debug("Failed to log timeline for plan approval", exc_info=True)

    return {"plan": plan, "plans_list": plans_list}


async def reject_plan(channel_id: str, plan_id: str) -> dict:
    """Reject a plan → abandoned. Returns {"plan": dict}.

    Raises ValueError if plan not found or not in draft/approved status.
    """
    _raw, plans_list = await _read_plans_md(channel_id)

    plan = None
    for p in plans_list:
        if p["meta"].get("id") == plan_id:
            plan = p
            break

    if not plan:
        raise ValueError(f"Plan '{plan_id}' not found")
    if plan["status"] not in ("draft", "approved"):
        raise ValueError(f"Plan is [{plan['status']}], expected [draft] or [approved]")

    plan["status"] = "abandoned"
    await _write_plans_md(channel_id, plans_list)

    try:
        await append_timeline(channel_id, f"Plan rejected: **{plan['title']}** ({plan_id})")
    except Exception:
        logger.debug("Failed to log timeline for plan rejection", exc_info=True)

    return {"plan": plan}


async def resume_plan(channel_id: str, plan_id: str) -> dict:
    """Resume an executing plan. Returns {"plan": dict}.

    Raises ValueError if plan not found or not in executing status.
    """
    _raw, plans_list = await _read_plans_md(channel_id)

    plan = None
    for p in plans_list:
        if p["meta"].get("id") == plan_id:
            plan = p
            break

    if not plan:
        raise ValueError(f"Plan '{plan_id}' not found")
    if plan["status"] != "executing":
        raise ValueError(f"Plan is [{plan['status']}], expected [executing]")

    try:
        await append_timeline(channel_id, f"Plan resumed: **{plan['title']}** ({plan_id})")
    except Exception:
        logger.debug("Failed to log timeline for plan resume", exc_info=True)

    return {"plan": plan}
