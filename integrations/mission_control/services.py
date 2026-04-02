"""Mission Control service layer — DB-backed with write-through markdown rendering.

Source of truth: MC-owned SQLite at {WORKSPACE_ROOT}/mission_control/mc.db.
After every mutation, markdown is rendered to workspace files so context injection
(active .md files auto-injected) continues working unchanged.

Lazy migration: on first DB access per channel, if DB is empty but markdown exists,
import from markdown → DB.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timezone

from sqlalchemy import func, select

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
# Markdown rendering (write-through to workspace files)
# ---------------------------------------------------------------------------

async def _render_tasks_md(channel_id: str) -> str:
    """Query DB → serialize → write tasks.md to workspace."""
    from app.services.channel_workspace import ensure_channel_workspace, write_workspace_file
    from app.services.task_board import serialize_tasks_md

    columns = await _get_kanban_columns_as_dicts(channel_id)
    bot = await _resolve_bot(channel_id)
    await asyncio.to_thread(ensure_channel_workspace, channel_id, bot)
    content = serialize_tasks_md(columns)
    await asyncio.to_thread(write_workspace_file, channel_id, bot, "tasks.md", content)
    return content


async def _render_timeline_md(channel_id: str) -> str:
    """Query DB → serialize → write timeline.md to workspace."""
    from app.services.channel_workspace import ensure_channel_workspace, write_workspace_file
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McTimelineEvent

    async with await mc_session() as session:
        result = await session.execute(
            select(McTimelineEvent)
            .where(McTimelineEvent.channel_id == channel_id)
            .order_by(McTimelineEvent.event_date.desc(), McTimelineEvent.event_time.desc())
        )
        events = list(result.scalars().all())

    # Group by date, newest first
    by_date: dict[str, list[str]] = {}
    for ev in events:
        by_date.setdefault(ev.event_date, []).append(f"- {ev.event_time} \u2014 {ev.event}")

    lines: list[str] = []
    for d in sorted(by_date.keys(), reverse=True):
        lines.append(f"## {d}")
        lines.extend(by_date[d])
        lines.append("")

    content = "\n".join(lines).rstrip() + "\n" if lines else ""

    bot = await _resolve_bot(channel_id)
    await asyncio.to_thread(ensure_channel_workspace, channel_id, bot)
    await asyncio.to_thread(write_workspace_file, channel_id, bot, "timeline.md", content)
    return content


async def _render_plans_md(channel_id: str) -> str:
    """Query DB → serialize → write plans.md to workspace."""
    from app.services.channel_workspace import ensure_channel_workspace, write_workspace_file
    from app.services.plan_board import serialize_plans_md

    plans = await _get_plans_as_dicts(channel_id)
    bot = await _resolve_bot(channel_id)
    await asyncio.to_thread(ensure_channel_workspace, channel_id, bot)
    content = serialize_plans_md(plans)
    await asyncio.to_thread(write_workspace_file, channel_id, bot, "plans.md", content)
    return content


# ---------------------------------------------------------------------------
# DB → dict conversion helpers (legacy format for backward compat)
# ---------------------------------------------------------------------------

async def _get_kanban_columns_as_dicts(channel_id: str) -> list[dict]:
    """Query MC SQLite, return [{"name": ..., "cards": [...]}] in legacy format."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McKanbanCard, McKanbanColumn

    await _ensure_kanban_migrated(channel_id)

    async with await mc_session() as session:
        result = await session.execute(
            select(McKanbanColumn)
            .where(McKanbanColumn.channel_id == channel_id)
            .order_by(McKanbanColumn.position)
        )
        db_cols = list(result.scalars().all())

        columns: list[dict] = []
        for db_col in db_cols:
            cards_result = await session.execute(
                select(McKanbanCard)
                .where(McKanbanCard.column_id == db_col.id)
                .order_by(McKanbanCard.position)
            )
            db_cards = list(cards_result.scalars().all())

            cards = []
            for c in db_cards:
                meta: dict[str, str] = {"id": c.card_id}
                if c.assigned:
                    meta["assigned"] = c.assigned
                meta["priority"] = c.priority
                if c.created_date:
                    meta["created"] = c.created_date
                if c.tags:
                    meta["tags"] = c.tags
                if c.due_date:
                    meta["due"] = c.due_date
                if c.started_date:
                    meta["started"] = c.started_date
                if c.completed_date:
                    meta["completed"] = c.completed_date
                card_dict: dict = {
                    "title": c.title,
                    "meta": meta,
                    "description": c.description or "",
                }
                if c.plan_id:
                    card_dict["plan_id"] = c.plan_id
                    card_dict["plan_step_position"] = c.plan_step_position
                cards.append(card_dict)
            columns.append({"name": db_col.name, "id": db_col.id, "cards": cards})

    return columns


async def _get_plans_as_dicts(channel_id: str) -> list[dict]:
    """Query MC SQLite, return plans in legacy dict format."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlan

    await _ensure_plans_migrated(channel_id)

    async with await mc_session() as session:
        result = await session.execute(
            select(McPlan)
            .where(McPlan.channel_id == channel_id)
            .order_by(McPlan.created_at)
        )
        db_plans = list(result.scalars().all())

        plans: list[dict] = []
        for p in db_plans:
            # Eagerly load steps (already ordered by position via relationship)
            await session.refresh(p, ["steps"])
            meta: dict[str, str] = {"id": p.plan_id}
            if p.created_date:
                meta["created"] = p.created_date
            if p.approved_date:
                meta["approved"] = p.approved_date
            steps = []
            for s in p.steps:
                step_dict: dict = {
                    "position": s.position,
                    "status": s.status,
                    "content": s.content,
                    "requires_approval": s.requires_approval,
                    "started_at": s.started_at.isoformat() if s.started_at else None,
                    "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                }
                if s.task_id:
                    step_dict["task_id"] = s.task_id
                if s.result_summary:
                    step_dict["result_summary"] = s.result_summary
                steps.append(step_dict)
            plans.append({
                "title": p.title,
                "status": p.status,
                "meta": meta,
                "steps": steps,
                "notes": p.notes or "",
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            })

    return plans


async def get_single_plan(channel_id: str, plan_id: str) -> dict | None:
    """Query MC SQLite for one plan by plan_id + channel_id, return dict or None."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McKanbanCard, McPlan

    await _ensure_plans_migrated(channel_id)

    async with await mc_session() as session:
        result = await session.execute(
            select(McPlan)
            .where(McPlan.plan_id == plan_id)
            .where(McPlan.channel_id == channel_id)
        )
        p = result.scalar_one_or_none()
        if not p:
            return None

        await session.refresh(p, ["steps"])

        # Pre-fetch linked card IDs for all steps
        linked_cards: dict[int, str] = {}
        card_result = await session.execute(
            select(McKanbanCard.plan_step_position, McKanbanCard.card_id)
            .where(McKanbanCard.plan_id == plan_id)
            .where(McKanbanCard.channel_id == channel_id)
        )
        for row in card_result.all():
            if row[0] is not None:
                linked_cards[row[0]] = row[1]

        meta: dict[str, str] = {"id": p.plan_id}
        if p.created_date:
            meta["created"] = p.created_date
        if p.approved_date:
            meta["approved"] = p.approved_date
        steps = []
        for s in p.steps:
            step_dict: dict = {
                "position": s.position,
                "status": s.status,
                "content": s.content,
                "requires_approval": s.requires_approval,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
            }
            if s.task_id:
                step_dict["task_id"] = s.task_id
            if s.result_summary:
                step_dict["result_summary"] = s.result_summary
            if s.position in linked_cards:
                step_dict["linked_card_id"] = linked_cards[s.position]
            steps.append(step_dict)
        return {
            "title": p.title,
            "status": p.status,
            "meta": meta,
            "steps": steps,
            "notes": p.notes or "",
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        }


# ---------------------------------------------------------------------------
# Lazy migration — import markdown into DB on first access
# ---------------------------------------------------------------------------

# Track which channels have been checked to avoid re-checking every call
_kanban_migrated: set[str] = set()
_timeline_migrated: set[str] = set()
_plans_migrated: set[str] = set()

# Serialise migrations to prevent duplicate imports under concurrent access
_kanban_lock = asyncio.Lock()
_timeline_lock = asyncio.Lock()
_plans_lock = asyncio.Lock()


async def _ensure_kanban_migrated(channel_id: str) -> None:
    """If DB has no kanban data for this channel but markdown exists, import it."""
    if channel_id in _kanban_migrated:
        return

    async with _kanban_lock:
        if channel_id in _kanban_migrated:
            return

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McKanbanColumn

        async with await mc_session() as session:
            result = await session.execute(
                select(func.count()).select_from(McKanbanColumn)
                .where(McKanbanColumn.channel_id == channel_id)
            )
            count = result.scalar() or 0

        if count > 0:
            _kanban_migrated.add(channel_id)
            return

        # Try to import from markdown
        from app.services.channel_workspace import read_workspace_file
        from app.services.task_board import default_columns, parse_tasks_md

        try:
            bot = await _resolve_bot(channel_id)
            content = await asyncio.to_thread(read_workspace_file, channel_id, bot, "tasks.md")
            if content:
                columns = parse_tasks_md(content)
            else:
                columns = default_columns()
        except Exception:
            columns = default_columns()

        await _import_kanban_columns(channel_id, columns)
        _kanban_migrated.add(channel_id)


async def _import_kanban_columns(channel_id: str, columns: list[dict]) -> None:
    """Import parsed kanban columns into DB."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McKanbanCard, McKanbanColumn

    async with await mc_session() as session:
        for col_pos, col in enumerate(columns):
            db_col = McKanbanColumn(
                channel_id=channel_id,
                name=col["name"],
                position=col_pos,
            )
            session.add(db_col)
            await session.flush()  # get db_col.id

            for card_pos, card in enumerate(col.get("cards", [])):
                meta = card.get("meta", {})
                db_card = McKanbanCard(
                    channel_id=channel_id,
                    column_id=db_col.id,
                    card_id=meta.get("id", f"mc-{__import__('uuid').uuid4().hex[:6]}"),
                    title=card["title"],
                    description=card.get("description", ""),
                    priority=meta.get("priority", "medium"),
                    assigned=meta.get("assigned", ""),
                    tags=meta.get("tags", ""),
                    due_date=meta.get("due", ""),
                    position=card_pos,
                    created_date=meta.get("created", ""),
                    started_date=meta.get("started", ""),
                    completed_date=meta.get("completed", ""),
                )
                session.add(db_card)

        await session.commit()


async def _ensure_timeline_migrated(channel_id: str) -> None:
    """If DB has no timeline data for this channel but markdown exists, import it."""
    if channel_id in _timeline_migrated:
        return

    async with _timeline_lock:
        if channel_id in _timeline_migrated:
            return

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McTimelineEvent

        async with await mc_session() as session:
            result = await session.execute(
                select(func.count()).select_from(McTimelineEvent)
                .where(McTimelineEvent.channel_id == channel_id)
            )
            count = result.scalar() or 0

        if count > 0:
            _timeline_migrated.add(channel_id)
            return

        # Try to import from markdown
        from app.services.channel_workspace import read_workspace_file

        try:
            bot = await _resolve_bot(channel_id)
            content = await asyncio.to_thread(read_workspace_file, channel_id, bot, "timeline.md")
            if content:
                events = parse_timeline_md(content)
                async with await mc_session() as session:
                    for ev in events:
                        session.add(McTimelineEvent(
                            channel_id=channel_id,
                            event_date=ev["date"],
                            event_time=ev["time"],
                            event=ev["event"],
                        ))
                    await session.commit()
            _timeline_migrated.add(channel_id)
        except Exception:
            logger.debug("No timeline to migrate for channel %s", channel_id, exc_info=True)


async def _ensure_plans_migrated(channel_id: str) -> None:
    """If DB has no plan data for this channel but markdown exists, import it."""
    if channel_id in _plans_migrated:
        return

    async with _plans_lock:
        if channel_id in _plans_migrated:
            return

        from integrations.mission_control.db.engine import mc_session
        from integrations.mission_control.db.models import McPlan

        async with await mc_session() as session:
            result = await session.execute(
                select(func.count()).select_from(McPlan)
                .where(McPlan.channel_id == channel_id)
            )
            count = result.scalar() or 0

        if count > 0:
            _plans_migrated.add(channel_id)
            return

        # Try to import from markdown
        from app.services.channel_workspace import read_workspace_file
        from app.services.plan_board import parse_plans_md

        try:
            bot = await _resolve_bot(channel_id)
            content = await asyncio.to_thread(read_workspace_file, channel_id, bot, "plans.md")
            if content:
                plans = parse_plans_md(content)
                await _import_plans(channel_id, plans)
            _plans_migrated.add(channel_id)
        except Exception:
            logger.debug("No plans to migrate for channel %s", channel_id, exc_info=True)


async def _import_plans(channel_id: str, plans: list[dict]) -> None:
    """Import parsed plans into DB."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlan, McPlanStep

    async with await mc_session() as session:
        for p in plans:
            meta = p.get("meta", {})
            db_plan = McPlan(
                channel_id=channel_id,
                plan_id=meta.get("id", f"plan-{__import__('uuid').uuid4().hex[:6]}"),
                title=p["title"],
                status=p.get("status", "draft"),
                notes=p.get("notes", ""),
                created_date=meta.get("created", ""),
                approved_date=meta.get("approved", ""),
            )
            session.add(db_plan)
            await session.flush()

            for step in p.get("steps", []):
                session.add(McPlanStep(
                    plan_id=db_plan.id,
                    position=step["position"],
                    content=step["content"],
                    status=step.get("status", "pending"),
                ))

        await session.commit()


# ---------------------------------------------------------------------------
# Timeline operations
# ---------------------------------------------------------------------------

async def append_timeline(channel_id: str, event: str) -> None:
    """Append an event to timeline — writes to DB then renders markdown."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McTimelineEvent

    await _ensure_timeline_migrated(channel_id)

    now = datetime.now(timezone.utc).astimezone()
    event_date = now.strftime("%Y-%m-%d")
    event_time = now.strftime("%H:%M")

    async with await mc_session() as session:
        session.add(McTimelineEvent(
            channel_id=channel_id,
            event_date=event_date,
            event_time=event_time,
            event=event,
        ))
        await session.commit()

    await _render_timeline_md(channel_id)


def parse_timeline_md(content: str) -> list[dict]:
    """Parse timeline.md into structured event dicts.

    Returns list of ``{"date": "YYYY-MM-DD", "time": "HH:MM", "event": "..."}``
    in file order (newest first).
    """
    events: list[dict] = []
    current_date: str | None = None
    date_re = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})")
    entry_re = re.compile(r"^-\s+(\d{1,2}:\d{2})\s*[\u2014\u2013-]\s*(.+)")

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


async def get_card_history(channel_id: str, card_id: str, limit: int = 10) -> list[dict]:
    """Get timeline events mentioning a specific card."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McTimelineEvent

    await _ensure_timeline_migrated(channel_id)

    async with await mc_session() as session:
        result = await session.execute(
            select(McTimelineEvent)
            .where(McTimelineEvent.channel_id == channel_id)
            .where(McTimelineEvent.event.contains(card_id))
            .order_by(McTimelineEvent.event_date.desc(), McTimelineEvent.event_time.desc())
            .limit(limit)
        )
        return [
            {"date": ev.event_date, "time": ev.event_time, "event": ev.event}
            for ev in result.scalars().all()
        ]


async def get_timeline_events(channel_id: str) -> list[dict]:
    """Get timeline events from DB as dicts. Used by helpers/routers."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McTimelineEvent

    await _ensure_timeline_migrated(channel_id)

    async with await mc_session() as session:
        result = await session.execute(
            select(McTimelineEvent)
            .where(McTimelineEvent.channel_id == channel_id)
            .order_by(McTimelineEvent.event_date.desc(), McTimelineEvent.event_time.desc())
        )
        return [
            {"date": ev.event_date, "time": ev.event_time, "event": ev.event}
            for ev in result.scalars().all()
        ]


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
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McKanbanCard, McKanbanColumn

    await _ensure_kanban_migrated(channel_id)

    card_id = generate_card_id()
    today = date.today().isoformat()

    async with await mc_session() as session:
        # Find or create target column
        result = await session.execute(
            select(McKanbanColumn)
            .where(McKanbanColumn.channel_id == channel_id)
            .where(func.lower(McKanbanColumn.name) == column.lower())
            .limit(1)
        )
        db_col = result.scalar_one_or_none()

        if db_col is None:
            # Auto-create column; insert before "Done" if it exists
            max_pos_result = await session.execute(
                select(func.max(McKanbanColumn.position))
                .where(McKanbanColumn.channel_id == channel_id)
            )
            max_pos = max_pos_result.scalar() or 0

            # Check if a "Done" column exists to insert before it
            done_result = await session.execute(
                select(McKanbanColumn)
                .where(McKanbanColumn.channel_id == channel_id)
                .where(func.lower(McKanbanColumn.name) == "done")
            )
            done_col = done_result.scalar_one_or_none()
            if done_col:
                new_pos = done_col.position
                # Shift Done and everything after it
                await session.execute(
                    McKanbanColumn.__table__.update()
                    .where(McKanbanColumn.channel_id == channel_id)
                    .where(McKanbanColumn.position >= new_pos)
                    .values(position=McKanbanColumn.position + 1)
                )
            else:
                new_pos = max_pos + 1

            db_col = McKanbanColumn(
                channel_id=channel_id,
                name=column,
                position=new_pos,
            )
            session.add(db_col)
            await session.flush()

        # Count existing cards for position
        count_result = await session.execute(
            select(func.count()).select_from(McKanbanCard)
            .where(McKanbanCard.column_id == db_col.id)
        )
        next_pos = count_result.scalar() or 0

        db_card = McKanbanCard(
            channel_id=channel_id,
            column_id=db_col.id,
            card_id=card_id,
            title=title,
            description=description,
            priority=priority,
            assigned=assigned,
            tags=tags,
            due_date=due,
            position=next_pos,
            created_date=today,
        )
        session.add(db_card)
        await session.commit()

        actual_col_name = db_col.name

    # Render markdown
    await _render_tasks_md(channel_id)

    # Build legacy return dict
    meta: dict[str, str] = {"id": card_id}
    if assigned:
        meta["assigned"] = assigned
    meta["priority"] = priority
    meta["created"] = today
    if tags:
        meta["tags"] = tags
    if due:
        meta["due"] = due

    card = {"title": title, "meta": meta, "description": description}

    # Auto-log to timeline
    try:
        await append_timeline(
            channel_id,
            f"New card created: {card_id} \"{title}\" in **{actual_col_name}**",
        )
    except Exception:
        logger.debug("Failed to log timeline event for create_card", exc_info=True)

    return {"card": card, "column": actual_col_name, "card_id": card_id}


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
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McKanbanCard, McKanbanColumn

    await _ensure_kanban_migrated(channel_id)

    async with await mc_session() as session:
        # Find the card
        result = await session.execute(
            select(McKanbanCard)
            .where(McKanbanCard.card_id == card_id)
            .where(McKanbanCard.channel_id == channel_id)
        )
        db_card = result.scalar_one_or_none()
        if not db_card:
            raise ValueError(f"Card {card_id} not found")

        # Get source column
        source_col = await session.get(McKanbanColumn, db_card.column_id)
        source_col_name = source_col.name if source_col else "Unknown"

        if from_column and source_col_name.lower() != from_column.lower():
            raise ValueError(
                f"Card {card_id} is in '{source_col_name}', not '{from_column}'"
            )

        # Find or create target column
        target_result = await session.execute(
            select(McKanbanColumn)
            .where(McKanbanColumn.channel_id == channel_id)
            .where(func.lower(McKanbanColumn.name) == to_column.lower())
            .limit(1)
        )
        target_col = target_result.scalar_one_or_none()

        if target_col is None:
            max_pos_result = await session.execute(
                select(func.max(McKanbanColumn.position))
                .where(McKanbanColumn.channel_id == channel_id)
            )
            target_col = McKanbanColumn(
                channel_id=channel_id,
                name=to_column,
                position=(max_pos_result.scalar() or 0) + 1,
            )
            session.add(target_col)
            await session.flush()

        # Move card
        db_card.column_id = target_col.id

        # Count cards in target for position
        count_result = await session.execute(
            select(func.count()).select_from(McKanbanCard)
            .where(McKanbanCard.column_id == target_col.id)
            .where(McKanbanCard.id != db_card.id)
        )
        db_card.position = count_result.scalar() or 0

        # Add transition metadata
        today = date.today().isoformat()
        if to_column.lower() == "in progress":
            db_card.started_date = today
        elif to_column.lower() == "done":
            db_card.completed_date = today

        await session.commit()

        # Build legacy return dict
        meta: dict[str, str] = {"id": db_card.card_id}
        if db_card.assigned:
            meta["assigned"] = db_card.assigned
        meta["priority"] = db_card.priority
        if db_card.created_date:
            meta["created"] = db_card.created_date
        if db_card.tags:
            meta["tags"] = db_card.tags
        if db_card.due_date:
            meta["due"] = db_card.due_date
        if db_card.started_date:
            meta["started"] = db_card.started_date
        if db_card.completed_date:
            meta["completed"] = db_card.completed_date

        card_dict = {
            "title": db_card.title,
            "meta": meta,
            "description": db_card.description or "",
        }
        actual_target_name = target_col.name

    # Render markdown
    await _render_tasks_md(channel_id)

    # Auto-log to timeline
    try:
        await append_timeline(
            channel_id,
            f"Card {card_id} moved to **{actual_target_name}** (was: {source_col_name}) \u2014 \"{card_dict['title']}\"",
        )
    except Exception:
        logger.debug("Failed to log timeline event for move_card", exc_info=True)

    return {"card": card_dict, "from_column": source_col_name, "to_column": actual_target_name}


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
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McKanbanCard

    await _ensure_kanban_migrated(channel_id)

    async with await mc_session() as session:
        result = await session.execute(
            select(McKanbanCard)
            .where(McKanbanCard.card_id == card_id)
            .where(McKanbanCard.channel_id == channel_id)
        )
        db_card = result.scalar_one_or_none()
        if not db_card:
            raise ValueError(f"Card {card_id} not found")

        changes: list[str] = []
        if title is not None and title != db_card.title:
            db_card.title = title
            changes.append("title")
        if description is not None and description != (db_card.description or ""):
            db_card.description = description
            changes.append("description")
        if priority is not None and priority != db_card.priority:
            db_card.priority = priority
            changes.append("priority")
        if assigned is not None:
            db_card.assigned = assigned
            changes.append("assigned")
        if due is not None:
            db_card.due_date = due
            changes.append("due")
        if tags is not None:
            db_card.tags = tags
            changes.append("tags")

        if changes:
            await session.commit()

        # Build legacy return dict
        meta: dict[str, str] = {"id": db_card.card_id}
        if db_card.assigned:
            meta["assigned"] = db_card.assigned
        meta["priority"] = db_card.priority
        if db_card.created_date:
            meta["created"] = db_card.created_date
        if db_card.tags:
            meta["tags"] = db_card.tags
        if db_card.due_date:
            meta["due"] = db_card.due_date
        if db_card.started_date:
            meta["started"] = db_card.started_date
        if db_card.completed_date:
            meta["completed"] = db_card.completed_date

        card_dict = {
            "title": db_card.title,
            "meta": meta,
            "description": db_card.description or "",
        }

    if changes:
        await _render_tasks_md(channel_id)
        try:
            change_str = ", ".join(changes)
            await append_timeline(
                channel_id,
                f"Card {card_id} updated ({change_str}) \u2014 \"{card_dict['title']}\"",
            )
        except Exception:
            logger.debug("Failed to log timeline event for update_card", exc_info=True)

    return {"card": card_dict, "changes": changes}


# ---------------------------------------------------------------------------
# Column management operations
# ---------------------------------------------------------------------------

async def create_column(channel_id: str, name: str, position: int | None = None) -> dict:
    """Create a new kanban column. Returns {"id": str, "name": str, "position": int}."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McKanbanColumn

    await _ensure_kanban_migrated(channel_id)

    async with await mc_session() as session:
        if position is None:
            # Insert before "Done" if it exists, else at end
            done_result = await session.execute(
                select(McKanbanColumn)
                .where(McKanbanColumn.channel_id == channel_id)
                .where(func.lower(McKanbanColumn.name) == "done")
            )
            done_col = done_result.scalar_one_or_none()
            if done_col:
                position = done_col.position
                await session.execute(
                    McKanbanColumn.__table__.update()
                    .where(McKanbanColumn.channel_id == channel_id)
                    .where(McKanbanColumn.position >= position)
                    .values(position=McKanbanColumn.position + 1)
                )
            else:
                max_result = await session.execute(
                    select(func.max(McKanbanColumn.position))
                    .where(McKanbanColumn.channel_id == channel_id)
                )
                position = (max_result.scalar() or -1) + 1

        col = McKanbanColumn(channel_id=channel_id, name=name, position=position)
        session.add(col)
        await session.commit()
        col_id = col.id
        col_pos = col.position

    await _render_tasks_md(channel_id)
    try:
        await append_timeline(channel_id, f"Column created: **{name}**")
    except Exception:
        logger.debug("Failed to log timeline for column create", exc_info=True)

    return {"id": col_id, "name": name, "position": col_pos}


async def rename_column(channel_id: str, column_id: str, name: str) -> dict:
    """Rename a kanban column. Returns {"id": str, "name": str}."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McKanbanColumn

    async with await mc_session() as session:
        col = await session.get(McKanbanColumn, column_id)
        if not col or col.channel_id != channel_id:
            raise ValueError(f"Column {column_id} not found")

        # Check for duplicate names (case-insensitive)
        dup_result = await session.execute(
            select(McKanbanColumn)
            .where(McKanbanColumn.channel_id == channel_id)
            .where(func.lower(McKanbanColumn.name) == name.lower())
            .where(McKanbanColumn.id != column_id)
        )
        if dup_result.scalar_one_or_none():
            raise ValueError(f"Column '{name}' already exists")

        old_name = col.name
        col.name = name
        await session.commit()

    await _render_tasks_md(channel_id)
    try:
        await append_timeline(channel_id, f"Column renamed: **{old_name}** → **{name}**")
    except Exception:
        logger.debug("Failed to log timeline for column rename", exc_info=True)

    return {"id": column_id, "name": name}


async def delete_column(channel_id: str, column_id: str) -> None:
    """Delete a kanban column. Raises ValueError if column has cards."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McKanbanCard, McKanbanColumn

    async with await mc_session() as session:
        col = await session.get(McKanbanColumn, column_id)
        if not col or col.channel_id != channel_id:
            raise ValueError(f"Column {column_id} not found")

        card_count = (await session.execute(
            select(func.count()).select_from(McKanbanCard)
            .where(McKanbanCard.column_id == column_id)
        )).scalar() or 0

        if card_count > 0:
            raise ValueError(f"Column '{col.name}' has cards — move or delete them first")

        col_name = col.name
        await session.delete(col)
        await session.commit()

    await _render_tasks_md(channel_id)
    try:
        await append_timeline(channel_id, f"Column deleted: **{col_name}**")
    except Exception:
        logger.debug("Failed to log timeline for column delete", exc_info=True)


async def reorder_columns(channel_id: str, column_ids: list[str]) -> None:
    """Set column positions from an ordered list of column IDs."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McKanbanColumn

    async with await mc_session() as session:
        for i, col_id in enumerate(column_ids):
            col = await session.get(McKanbanColumn, col_id)
            if not col or col.channel_id != channel_id:
                raise ValueError(f"Column {col_id} not found in channel")
            col.position = i
        await session.commit()

    await _render_tasks_md(channel_id)
    try:
        await append_timeline(channel_id, "Columns reordered")
    except Exception:
        logger.debug("Failed to log timeline for column reorder", exc_info=True)


# ---------------------------------------------------------------------------
# Plan ↔ Kanban bridge
# ---------------------------------------------------------------------------

async def create_cards_from_plan(channel_id: str, plan_id: str) -> list[str]:
    """Create kanban cards for each step of a plan. Returns list of card_ids.

    Guard against duplicates: if cards already exist for this plan_id, returns [].
    """
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McKanbanCard, McPlan

    await _ensure_kanban_migrated(channel_id)

    # Duplicate guard
    async with await mc_session() as session:
        existing = (await session.execute(
            select(func.count()).select_from(McKanbanCard)
            .where(McKanbanCard.channel_id == channel_id)
            .where(McKanbanCard.plan_id == plan_id)
        )).scalar() or 0

    if existing > 0:
        return []

    # Get plan steps
    async with await mc_session() as session:
        result = await session.execute(
            select(McPlan)
            .where(McPlan.plan_id == plan_id)
            .where(McPlan.channel_id == channel_id)
        )
        plan = result.scalar_one_or_none()
        if not plan:
            raise ValueError(f"Plan '{plan_id}' not found")

        await session.refresh(plan, ["steps"])
        steps = sorted(plan.steps, key=lambda s: s.position)
        plan_title = plan.title

    # Create a card for each step
    card_ids: list[str] = []
    for step in steps:
        title = step.content[:100]
        result = await create_card(
            channel_id,
            title=title,
            column="Backlog",
            tags=f"plan:{plan_id}",
            description=step.content,
        )
        card_id = result["card_id"]
        card_ids.append(card_id)

        # Link card to plan
        async with await mc_session() as session:
            card_result = await session.execute(
                select(McKanbanCard).where(McKanbanCard.card_id == card_id)
            )
            card = card_result.scalar_one()
            card.plan_id = plan_id
            card.plan_step_position = step.position
            await session.commit()

    try:
        await append_timeline(
            channel_id,
            f"Cards created from plan '{plan_title}' ({plan_id})",
        )
    except Exception:
        logger.debug("Failed to log timeline for plan card creation", exc_info=True)

    return card_ids


async def move_plan_card(
    channel_id: str, plan_id: str, step_position: int, to_column: str,
) -> None:
    """Move the kanban card linked to a plan step. Silently no-ops if no card found."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McKanbanCard

    try:
        async with await mc_session() as session:
            result = await session.execute(
                select(McKanbanCard)
                .where(McKanbanCard.plan_id == plan_id)
                .where(McKanbanCard.plan_step_position == step_position)
                .where(McKanbanCard.channel_id == channel_id)
            )
            card = result.scalar_one_or_none()

        if card:
            await move_card(channel_id, card.card_id, to_column)
    except Exception:
        logger.debug(
            "Best-effort move_plan_card failed for %s step %d",
            plan_id, step_position, exc_info=True,
        )


# ---------------------------------------------------------------------------
# Plan template operations
# ---------------------------------------------------------------------------

async def list_plan_templates() -> list[dict]:
    """List all plan templates."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlanTemplate

    async with await mc_session() as session:
        result = await session.execute(
            select(McPlanTemplate).order_by(McPlanTemplate.created_at.desc())
        )
        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "steps_json": t.steps_json,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in result.scalars().all()
        ]


async def get_plan_template(template_id: str) -> dict | None:
    """Get a single plan template by ID."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlanTemplate

    async with await mc_session() as session:
        tpl = await session.get(McPlanTemplate, template_id)
        if not tpl:
            return None
        return {
            "id": tpl.id,
            "name": tpl.name,
            "description": tpl.description,
            "steps_json": tpl.steps_json,
            "created_at": tpl.created_at.isoformat() if tpl.created_at else None,
            "updated_at": tpl.updated_at.isoformat() if tpl.updated_at else None,
        }


async def create_plan_template(
    name: str, description: str, steps: list[dict],
) -> dict:
    """Create a plan template. steps = [{content, requires_approval?}]."""
    import json as _json

    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlanTemplate

    async with await mc_session() as session:
        tpl = McPlanTemplate(
            name=name,
            description=description,
            steps_json=_json.dumps(steps),
        )
        session.add(tpl)
        await session.commit()
        return {
            "id": tpl.id,
            "name": tpl.name,
            "description": tpl.description,
            "steps_json": tpl.steps_json,
            "created_at": tpl.created_at.isoformat() if tpl.created_at else None,
            "updated_at": tpl.updated_at.isoformat() if tpl.updated_at else None,
        }


async def delete_plan_template(template_id: str) -> None:
    """Delete a plan template."""
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlanTemplate

    async with await mc_session() as session:
        tpl = await session.get(McPlanTemplate, template_id)
        if not tpl:
            raise ValueError(f"Template '{template_id}' not found")
        await session.delete(tpl)
        await session.commit()


async def create_plan_from_template(
    template_id: str, channel_id: str, title: str, notes: str = "",
) -> str:
    """Create a draft plan from a template. Returns the new plan_id."""
    import json as _json

    from app.services.plan_board import generate_plan_id
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlan, McPlanStep, McPlanTemplate

    await _ensure_plans_migrated(channel_id)

    async with await mc_session() as session:
        tpl = await session.get(McPlanTemplate, template_id)
        if not tpl:
            raise ValueError(f"Template '{template_id}' not found")
        steps = _json.loads(tpl.steps_json)

    new_plan_id = generate_plan_id()

    async with await mc_session() as session:
        plan = McPlan(
            channel_id=channel_id,
            plan_id=new_plan_id,
            title=title,
            status="draft",
            notes=notes,
            created_date=date.today().isoformat(),
        )
        session.add(plan)
        await session.flush()

        for i, step in enumerate(steps, 1):
            session.add(McPlanStep(
                plan_id=plan.id,
                position=i,
                content=step.get("content", ""),
                status="pending",
                requires_approval=step.get("requires_approval", False),
            ))
        await session.commit()

    await _render_plans_md(channel_id)
    try:
        await append_timeline(channel_id, f"Plan drafted from template: **{title}** ({new_plan_id})")
    except Exception:
        logger.debug("Failed to log timeline for plan from template", exc_info=True)

    return new_plan_id


async def save_plan_as_template(
    channel_id: str, plan_id: str, name: str, description: str = "",
) -> dict:
    """Save an existing plan's steps as a reusable template."""
    import json as _json

    plan = await get_single_plan(channel_id, plan_id)
    if not plan:
        raise ValueError(f"Plan '{plan_id}' not found")

    steps = [
        {
            "content": s["content"],
            "requires_approval": s.get("requires_approval", False),
        }
        for s in plan["steps"]
    ]

    return await create_plan_template(name, description, steps)


# ---------------------------------------------------------------------------
# Export operations
# ---------------------------------------------------------------------------

async def export_kanban_md(channel_id: str) -> str:
    """Export kanban board as markdown."""
    from app.services.task_board import serialize_tasks_md

    columns = await _get_kanban_columns_as_dicts(channel_id)
    return serialize_tasks_md(columns)


async def export_kanban_json(channel_id: str) -> list[dict]:
    """Export kanban board as JSON-serializable list of columns."""
    return await _get_kanban_columns_as_dicts(channel_id)


async def export_plan_md(channel_id: str, plan_id: str) -> str:
    """Export a single plan as markdown."""
    from app.services.plan_board import serialize_plans_md

    plan = await get_single_plan(channel_id, plan_id)
    if not plan:
        raise ValueError(f"Plan '{plan_id}' not found")
    return serialize_plans_md([plan])


async def export_plan_json(channel_id: str, plan_id: str) -> dict:
    """Export a single plan as JSON-serializable dict."""
    plan = await get_single_plan(channel_id, plan_id)
    if not plan:
        raise ValueError(f"Plan '{plan_id}' not found")
    return plan


# ---------------------------------------------------------------------------
# Plan operations (shared by tools + router)
# ---------------------------------------------------------------------------

async def approve_plan(channel_id: str, plan_id: str) -> dict:
    """Approve a draft plan -> approved. Returns {"plan": dict, "plans_list": list}.

    Raises ValueError if plan not found or not in draft status.
    """
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlan

    await _ensure_plans_migrated(channel_id)

    async with await mc_session() as session:
        result = await session.execute(
            select(McPlan)
            .where(McPlan.plan_id == plan_id)
            .where(McPlan.channel_id == channel_id)
        )
        db_plan = result.scalar_one_or_none()

        if not db_plan:
            raise ValueError(f"Plan '{plan_id}' not found")
        if db_plan.status != "draft":
            raise ValueError(f"Plan is [{db_plan.status}], expected [draft]")

        db_plan.status = "approved"
        db_plan.approved_date = date.today().isoformat()
        await session.commit()

    plans_list = await _get_plans_as_dicts(channel_id)
    plan_dict = next((p for p in plans_list if p["meta"].get("id") == plan_id), None)

    await _render_plans_md(channel_id)

    try:
        await append_timeline(channel_id, f"Plan approved: **{db_plan.title}** ({plan_id})")
    except Exception:
        logger.debug("Failed to log timeline for plan approval", exc_info=True)

    # Auto-create kanban cards from plan steps
    try:
        await create_cards_from_plan(channel_id, plan_id)
    except Exception:
        logger.debug("Failed to create cards from plan on approval", exc_info=True)

    return {"plan": plan_dict or {}, "plans_list": plans_list}


async def reject_plan(channel_id: str, plan_id: str) -> dict:
    """Reject a plan -> abandoned. Returns {"plan": dict}.

    Raises ValueError if plan not found or not in draft/approved status.
    """
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlan

    await _ensure_plans_migrated(channel_id)

    async with await mc_session() as session:
        result = await session.execute(
            select(McPlan)
            .where(McPlan.plan_id == plan_id)
            .where(McPlan.channel_id == channel_id)
        )
        db_plan = result.scalar_one_or_none()

        if not db_plan:
            raise ValueError(f"Plan '{plan_id}' not found")
        if db_plan.status not in ("draft", "approved"):
            raise ValueError(f"Plan is [{db_plan.status}], expected [draft] or [approved]")

        db_plan.status = "abandoned"
        await session.commit()
        title = db_plan.title

    plans_list = await _get_plans_as_dicts(channel_id)
    plan_dict = next((p for p in plans_list if p["meta"].get("id") == plan_id), None)

    await _render_plans_md(channel_id)

    try:
        await append_timeline(channel_id, f"Plan rejected: **{title}** ({plan_id})")
    except Exception:
        logger.debug("Failed to log timeline for plan rejection", exc_info=True)

    return {"plan": plan_dict or {}}


async def resume_plan(channel_id: str, plan_id: str) -> dict:
    """Resume an executing or awaiting_approval plan. Returns {"plan": dict}.

    Raises ValueError if plan not found or not in executing/awaiting_approval status.
    """
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlan

    await _ensure_plans_migrated(channel_id)

    async with await mc_session() as session:
        result = await session.execute(
            select(McPlan)
            .where(McPlan.plan_id == plan_id)
            .where(McPlan.channel_id == channel_id)
        )
        db_plan = result.scalar_one_or_none()

        if not db_plan:
            raise ValueError(f"Plan '{plan_id}' not found")
        if db_plan.status not in ("executing", "awaiting_approval"):
            raise ValueError(f"Plan is [{db_plan.status}], expected [executing] or [awaiting_approval]")

        # If awaiting_approval, transition back to executing
        if db_plan.status == "awaiting_approval":
            db_plan.status = "executing"
            await session.commit()

        title = db_plan.title

    plans_list = await _get_plans_as_dicts(channel_id)
    plan_dict = next((p for p in plans_list if p["meta"].get("id") == plan_id), None)

    await _render_plans_md(channel_id)

    try:
        await append_timeline(channel_id, f"Plan resumed: **{title}** ({plan_id})")
    except Exception:
        logger.debug("Failed to log timeline for plan resume", exc_info=True)

    return {"plan": plan_dict or {}}


# ---------------------------------------------------------------------------
# Legacy helpers — kept for backward compat (used by tools/plans.py)
# ---------------------------------------------------------------------------

async def _read_plans_md(channel_id: str) -> tuple[str, list[dict]]:
    """Read plans from DB and return in legacy format (content, plans_list)."""
    plans = await _get_plans_as_dicts(channel_id)
    from app.services.plan_board import serialize_plans_md
    content = serialize_plans_md(plans) if plans else ""
    return content, plans


async def _write_plans_md(channel_id: str, plans: list[dict]) -> str:
    """Write plans to DB from dict format, then render markdown.

    This is a compatibility shim for tools/plans.py which still manipulates dicts.
    It syncs the dict state into the DB.
    """
    from integrations.mission_control.db.engine import mc_session
    from integrations.mission_control.db.models import McPlan, McPlanStep

    await _ensure_plans_migrated(channel_id)

    async with await mc_session() as session:
        for p in plans:
            meta = p.get("meta", {})
            pid = meta.get("id", "")
            if not pid:
                continue

            result = await session.execute(
                select(McPlan).where(McPlan.plan_id == pid)
            )
            db_plan = result.scalar_one_or_none()

            if db_plan:
                # Update existing
                db_plan.title = p["title"]
                db_plan.status = p["status"]
                db_plan.notes = p.get("notes", "")
                if meta.get("approved"):
                    db_plan.approved_date = meta["approved"]

                # Sync steps
                await session.refresh(db_plan, ["steps"])
                existing_steps = {s.position: s for s in db_plan.steps}
                for step_dict in p.get("steps", []):
                    pos = step_dict["position"]
                    if pos in existing_steps:
                        existing_steps[pos].status = step_dict["status"]
                        existing_steps[pos].content = step_dict["content"]
                    else:
                        session.add(McPlanStep(
                            plan_id=db_plan.id,
                            position=pos,
                            content=step_dict["content"],
                            status=step_dict.get("status", "pending"),
                        ))
            else:
                # Insert new plan
                db_plan = McPlan(
                    channel_id=channel_id,
                    plan_id=pid,
                    title=p["title"],
                    status=p.get("status", "draft"),
                    notes=p.get("notes", ""),
                    created_date=meta.get("created", ""),
                    approved_date=meta.get("approved", ""),
                )
                session.add(db_plan)
                await session.flush()

                for step_dict in p.get("steps", []):
                    session.add(McPlanStep(
                        plan_id=db_plan.id,
                        position=step_dict["position"],
                        content=step_dict["content"],
                        status=step_dict.get("status", "pending"),
                    ))

        await session.commit()

    return await _render_plans_md(channel_id)
