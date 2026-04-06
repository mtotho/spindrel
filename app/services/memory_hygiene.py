"""Memory hygiene scheduler — periodic cross-channel memory curation.

Called from the task_worker loop. Checks which workspace-files bots are due
for a hygiene run, optionally checks for recent activity, and creates
standard agent tasks (task_type="memory_hygiene") to perform the curation.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEFAULT_MEMORY_HYGIENE_PROMPT, settings
from app.db.models import Bot as BotRow, Message, Task

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resolution helpers (bot override > global default)
# ---------------------------------------------------------------------------

def resolve_enabled(bot_row: BotRow) -> bool:
    """Whether hygiene is enabled for this bot. Requires workspace-files scheme."""
    if bot_row.memory_scheme != "workspace-files":
        return False
    if bot_row.memory_hygiene_enabled is not None:
        return bot_row.memory_hygiene_enabled
    return settings.MEMORY_HYGIENE_ENABLED


def resolve_interval(bot_row: BotRow) -> int:
    """Interval in hours between hygiene runs."""
    if bot_row.memory_hygiene_interval_hours is not None:
        return bot_row.memory_hygiene_interval_hours
    return settings.MEMORY_HYGIENE_INTERVAL_HOURS


def resolve_only_if_active(bot_row: BotRow) -> bool:
    """Whether to skip hygiene if no user activity since last run."""
    if bot_row.memory_hygiene_only_if_active is not None:
        return bot_row.memory_hygiene_only_if_active
    return settings.MEMORY_HYGIENE_ONLY_IF_ACTIVE


def resolve_prompt(bot_row: BotRow) -> str:
    """Resolve the hygiene prompt: bot > global > built-in default."""
    if bot_row.memory_hygiene_prompt:
        return bot_row.memory_hygiene_prompt
    if settings.MEMORY_HYGIENE_PROMPT:
        return settings.MEMORY_HYGIENE_PROMPT
    return DEFAULT_MEMORY_HYGIENE_PROMPT


def resolve_model(bot_row: BotRow) -> str | None:
    """Resolve the model for hygiene runs: bot > global > None (use bot default)."""
    val = getattr(bot_row, "memory_hygiene_model", None)
    if val:
        return val
    if settings.MEMORY_HYGIENE_MODEL:
        return settings.MEMORY_HYGIENE_MODEL
    return None


def resolve_model_provider_id(bot_row: BotRow) -> str | None:
    """Resolve the model provider for hygiene runs: bot > global > None (use bot default)."""
    val = getattr(bot_row, "memory_hygiene_model_provider_id", None)
    if val:
        return val
    if settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID:
        return settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID
    return None


def resolve_target_hour(bot_row: BotRow) -> int:
    """Resolve target hour: bot override > global > -1 (disabled)."""
    val = getattr(bot_row, "memory_hygiene_target_hour", None)
    if val is not None:
        return val
    return settings.MEMORY_HYGIENE_TARGET_HOUR


# ---------------------------------------------------------------------------
# Activity check
# ---------------------------------------------------------------------------

async def _has_activity_since(bot_id: str, since: datetime, db: AsyncSession) -> bool:
    """Check if any user messages exist across the bot's channels since timestamp.

    Includes channels where the bot is a member (via ChannelBotMember).
    """
    from app.db.models import Channel, Session
    from app.services.channels import bot_channel_filter

    # Join Message → Session → Channel to find user messages across all
    # channels belonging to this bot (primary or member).
    count = (await db.execute(
        select(func.count())
        .select_from(Message)
        .join(Session, Message.session_id == Session.id)
        .join(Channel, Session.channel_id == Channel.id)
        .where(
            bot_channel_filter(bot_id),
            Message.role == "user",
            Message.created_at >= since,
        )
    )).scalar() or 0
    return count > 0


# ---------------------------------------------------------------------------
# Task creation
# ---------------------------------------------------------------------------

async def create_hygiene_task(bot_id: str, db: AsyncSession, *, auto_commit: bool = True) -> uuid.UUID:
    """Create a memory_hygiene task for the given bot. Returns the task ID.

    When called from the scheduler, pass auto_commit=False so the caller can
    commit the task + schedule update atomically.
    """
    bot_row = await db.get(BotRow, bot_id)
    if not bot_row:
        raise ValueError(f"Bot not found: {bot_id}")

    prompt = resolve_prompt(bot_row)

    # Build execution_config with model overrides if set
    exec_cfg: dict | None = None
    model = resolve_model(bot_row)
    provider = resolve_model_provider_id(bot_row)
    if model or provider:
        exec_cfg = {}
        if model:
            exec_cfg["model_override"] = model
        if provider:
            exec_cfg["model_provider_id_override"] = provider

    task = Task(
        id=uuid.uuid4(),
        bot_id=bot_id,
        prompt=prompt,
        title=f"Memory hygiene: {bot_id}",
        task_type="memory_hygiene",
        status="pending",
        run_at=datetime.now(timezone.utc),
        dispatch_type="none",
        execution_config=exec_cfg,
        # No channel_id — cross-channel run
        channel_id=None,
        session_id=None,
        client_id=None,
    )
    db.add(task)
    if auto_commit:
        await db.commit()

    logger.info("Created memory_hygiene task %s for bot %s", task.id, bot_id)
    return task.id


# ---------------------------------------------------------------------------
# Stagger offset (spread bots across interval to avoid thundering herd)
# ---------------------------------------------------------------------------

def _stagger_offset_minutes(bot_id: str, interval_hours: int, *, target_mode: bool = False) -> int:
    """Deterministic offset from bot_id hash.

    When target_mode is True, the window is clamped to 60 minutes (bots
    stagger within a 1-hour window around the target hour).
    Otherwise, the window spans the full interval.
    """
    if target_mode:
        window = 60
    else:
        window = max(interval_hours * 60, 1)  # guard against zero
    h = int(hashlib.md5(bot_id.encode()).hexdigest(), 16)
    return h % window


# ---------------------------------------------------------------------------
# Target-hour scheduling
# ---------------------------------------------------------------------------

def _next_target_run(
    bot_id: str,
    target_hour: int,
    interval_hours: int,
    now_utc: datetime,
    *,
    after_run: bool = False,
) -> datetime:
    """Compute the next run time anchored to ``target_hour`` in local time.

    ``target_hour`` is 0-23 in the server's configured TIMEZONE.

    On bootstrap (after_run=False):
        Find the next occurrence of target_hour that is in the future,
        then add a deterministic stagger offset (0-59 min).

    After a completed run (after_run=True):
        Find the next occurrence of target_hour that is >= now + interval_hours,
        then add the stagger offset.  This ensures we never schedule sooner
        than the configured interval while staying anchored to the target hour.
    """
    tz = ZoneInfo(settings.TIMEZONE)
    now_local = now_utc.astimezone(tz)

    # Build candidate: today at target_hour in local time
    candidate = now_local.replace(hour=target_hour, minute=0, second=0, microsecond=0)

    if after_run:
        # Must be >= now + interval
        earliest = now_local + timedelta(hours=interval_hours)
        while candidate < earliest:
            candidate += timedelta(days=1)
    else:
        # Bootstrap: must be in the future
        while candidate <= now_local:
            candidate += timedelta(days=1)

    # Convert to UTC, add deterministic stagger
    candidate_utc = candidate.astimezone(timezone.utc)
    stagger = _stagger_offset_minutes(bot_id, interval_hours, target_mode=True)
    return candidate_utc + timedelta(minutes=stagger)


# ---------------------------------------------------------------------------
# Schedule bootstrap (called when hygiene is first enabled via admin API)
# ---------------------------------------------------------------------------

async def bootstrap_hygiene_schedule(bot_row: BotRow, db: AsyncSession) -> None:
    """Set next_hygiene_run_at when hygiene is enabled for the first time.

    Uses a deterministic stagger offset so bots with the same interval
    don't all fire at the same time.
    """
    interval = resolve_interval(bot_row)
    target_hour = resolve_target_hour(bot_row)

    if target_hour >= 0:
        now_utc = datetime.now(timezone.utc)
        bot_row.next_hygiene_run_at = _next_target_run(
            bot_row.id, target_hour, interval, now_utc, after_run=False,
        )
    else:
        offset = _stagger_offset_minutes(bot_row.id, interval)
        bot_row.next_hygiene_run_at = datetime.now(timezone.utc) + timedelta(minutes=offset)

    await db.commit()
    logger.info("Bootstrapped hygiene schedule for bot %s: next run at %s", bot_row.id, bot_row.next_hygiene_run_at)


# ---------------------------------------------------------------------------
# Compute next run (used by scheduler and recalc-on-change)
# ---------------------------------------------------------------------------

def _compute_next_run(bot_row: BotRow, now_utc: datetime, *, after_run: bool = False) -> datetime:
    """Compute the next hygiene run time for a bot.

    Centralises the target_hour vs plain-interval logic.
    """
    interval = resolve_interval(bot_row)
    target_hour = resolve_target_hour(bot_row)

    if target_hour >= 0:
        return _next_target_run(
            bot_row.id, target_hour, interval, now_utc, after_run=after_run,
        )
    return now_utc + timedelta(hours=interval)


# ---------------------------------------------------------------------------
# Main scheduler — called from task_worker loop
# ---------------------------------------------------------------------------

async def check_memory_hygiene() -> None:
    """Check all workspace-files bots and create hygiene tasks for those that are due."""
    from app.db.engine import async_session

    now = datetime.now(timezone.utc)

    async with async_session() as db:
        # Find bots with workspace-files memory scheme
        rows = (await db.execute(
            select(BotRow).where(BotRow.memory_scheme == "workspace-files")
        )).scalars().all()

        for bot_row in rows:
            try:
                if not resolve_enabled(bot_row):
                    continue

                # First-time bootstrap: stagger instead of running immediately
                if bot_row.next_hygiene_run_at is None:
                    target_hour = resolve_target_hour(bot_row)
                    interval = resolve_interval(bot_row)
                    if target_hour >= 0:
                        bot_row.next_hygiene_run_at = _next_target_run(
                            bot_row.id, target_hour, interval, now, after_run=False,
                        )
                    else:
                        offset = _stagger_offset_minutes(bot_row.id, interval)
                        bot_row.next_hygiene_run_at = now + timedelta(minutes=offset)
                    await db.commit()
                    logger.info("Bootstrapped hygiene for bot %s: first run at %s", bot_row.id, bot_row.next_hygiene_run_at)
                    continue

                # Skip if not yet due
                if bot_row.next_hygiene_run_at > now:
                    continue

                interval = resolve_interval(bot_row)

                # Activity check (if enabled)
                if resolve_only_if_active(bot_row):
                    since = bot_row.last_hygiene_run_at or (now - timedelta(hours=interval))
                    if not await _has_activity_since(bot_row.id, since, db):
                        # No activity — advance schedule without running
                        bot_row.next_hygiene_run_at = _compute_next_run(bot_row, now, after_run=True)
                        await db.commit()
                        logger.debug("Skipped hygiene for bot %s: no activity since %s", bot_row.id, since)
                        continue

                # Dedup: check if there's already a pending/running hygiene task
                existing = (await db.execute(
                    select(func.count())
                    .select_from(Task)
                    .where(
                        Task.bot_id == bot_row.id,
                        Task.task_type == "memory_hygiene",
                        Task.status.in_(["pending", "running"]),
                    )
                )).scalar() or 0
                if existing > 0:
                    logger.debug("Skipped hygiene for bot %s: task already in progress", bot_row.id)
                    continue

                # Create the task + advance schedule atomically
                await create_hygiene_task(bot_row.id, db, auto_commit=False)
                bot_row.last_hygiene_run_at = now
                bot_row.next_hygiene_run_at = _compute_next_run(bot_row, now, after_run=True)
                await db.commit()

                logger.info("Scheduled hygiene for bot %s, next at %s", bot_row.id, bot_row.next_hygiene_run_at)

            except Exception:
                logger.exception("Error checking hygiene for bot %s", bot_row.id)
