"""Memory hygiene scheduler — periodic cross-channel memory curation.

Called from the task_worker loop. Checks which workspace-files bots are due
for maintenance and/or skill review runs, optionally checks for recent
activity, and creates standard agent tasks to perform the curation.

Two job types:
- memory_hygiene: lightweight maintenance (curate files, promote logs, archive)
- skill_review: reasoning-heavy review (cross-channel reflection, skill pruning/creation)
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import DEFAULT_MEMORY_HYGIENE_PROMPT, DEFAULT_SKILL_REVIEW_PROMPT, settings
from app.db.models import Bot as BotRow, Message, Task

logger = logging.getLogger(__name__)

# The two job types supported by the hygiene scheduler.
JobType = Literal["memory_hygiene", "skill_review"]

# Column name prefixes and setting name prefixes for each job type.
_JOB_META = {
    "memory_hygiene": {
        "col_enabled": "memory_hygiene_enabled",
        "col_interval": "memory_hygiene_interval_hours",
        "col_prompt": "memory_hygiene_prompt",
        "col_only_if_active": "memory_hygiene_only_if_active",
        "col_model": "memory_hygiene_model",
        "col_model_provider": "memory_hygiene_model_provider_id",
        "col_target_hour": "memory_hygiene_target_hour",
        "col_extra_instructions": "memory_hygiene_extra_instructions",
        "col_last_run": "last_hygiene_run_at",
        "col_next_run": "next_hygiene_run_at",
        "setting_enabled": "MEMORY_HYGIENE_ENABLED",
        "setting_interval": "MEMORY_HYGIENE_INTERVAL_HOURS",
        "setting_prompt": "MEMORY_HYGIENE_PROMPT",
        "setting_only_if_active": "MEMORY_HYGIENE_ONLY_IF_ACTIVE",
        "setting_model": "MEMORY_HYGIENE_MODEL",
        "setting_model_provider": "MEMORY_HYGIENE_MODEL_PROVIDER_ID",
        "setting_target_hour": "MEMORY_HYGIENE_TARGET_HOUR",
        "default_prompt": DEFAULT_MEMORY_HYGIENE_PROMPT,
        "task_title": "Memory maintenance",
    },
    "skill_review": {
        "col_enabled": "skill_review_enabled",
        "col_interval": "skill_review_interval_hours",
        "col_prompt": "skill_review_prompt",
        "col_only_if_active": "skill_review_only_if_active",
        "col_model": "skill_review_model",
        "col_model_provider": "skill_review_model_provider_id",
        "col_target_hour": "skill_review_target_hour",
        "col_extra_instructions": "skill_review_extra_instructions",
        "col_last_run": "last_skill_review_run_at",
        "col_next_run": "next_skill_review_run_at",
        "setting_enabled": "SKILL_REVIEW_ENABLED",
        "setting_interval": "SKILL_REVIEW_INTERVAL_HOURS",
        "setting_prompt": "SKILL_REVIEW_PROMPT",
        "setting_only_if_active": "SKILL_REVIEW_ONLY_IF_ACTIVE",
        "setting_model": "SKILL_REVIEW_MODEL",
        "setting_model_provider": "SKILL_REVIEW_MODEL_PROVIDER_ID",
        "setting_target_hour": "SKILL_REVIEW_TARGET_HOUR",
        "default_prompt": DEFAULT_SKILL_REVIEW_PROMPT,
        "task_title": "Skill review",
    },
}


# ---------------------------------------------------------------------------
# Unified config resolution
# ---------------------------------------------------------------------------

@dataclass
class JobConfig:
    """Resolved configuration for a single hygiene job type."""
    enabled: bool
    interval_hours: int
    prompt: str
    only_if_active: bool
    model: str | None
    model_provider_id: str | None
    target_hour: int
    extra_instructions: str | None


def _col(bot_row: BotRow, col_name: str):
    """Safe attribute access that returns None for missing columns.

    Unlike plain getattr, this also returns None for MagicMock-style objects
    where any attribute access returns a truthy value.
    """
    if not hasattr(type(bot_row), col_name) and not hasattr(bot_row, "__table__"):
        # MagicMock or similar — check if the attribute was explicitly set
        try:
            return bot_row.__dict__.get(col_name) if hasattr(bot_row, "__dict__") else getattr(bot_row, col_name, None)
        except Exception:
            return None
    return getattr(bot_row, col_name, None)


def resolve_config(bot_row: BotRow, job_type: JobType) -> JobConfig:
    """Resolve all config fields for a job type: bot override > global > default."""
    meta = _JOB_META[job_type]

    # For memory_hygiene, delegate to legacy helpers for consistency
    if job_type == "memory_hygiene":
        return JobConfig(
            enabled=resolve_enabled(bot_row),
            interval_hours=resolve_interval(bot_row),
            prompt=resolve_prompt(bot_row),
            only_if_active=resolve_only_if_active(bot_row),
            model=resolve_model(bot_row),
            model_provider_id=resolve_model_provider_id(bot_row),
            target_hour=resolve_target_hour(bot_row),
            extra_instructions=getattr(bot_row, "memory_hygiene_extra_instructions", None),
        )

    # skill_review: same pattern as legacy helpers but for skill_review columns
    if bot_row.memory_scheme != "workspace-files":
        return JobConfig(
            enabled=False, interval_hours=72, prompt="",
            only_if_active=False, model=None, model_provider_id=None,
            target_hour=-1, extra_instructions=None,
        )

    # Enabled
    bot_enabled = getattr(bot_row, "skill_review_enabled", None)
    enabled = bot_enabled if bot_enabled is not None else settings.SKILL_REVIEW_ENABLED

    # Interval
    bot_interval = getattr(bot_row, "skill_review_interval_hours", None)
    interval_hours = bot_interval if bot_interval is not None else settings.SKILL_REVIEW_INTERVAL_HOURS

    # Only-if-active
    bot_active = getattr(bot_row, "skill_review_only_if_active", None)
    only_if_active = bot_active if bot_active is not None else settings.SKILL_REVIEW_ONLY_IF_ACTIVE

    # Prompt
    bot_prompt = getattr(bot_row, "skill_review_prompt", None)
    if bot_prompt:
        prompt = bot_prompt
    elif settings.SKILL_REVIEW_PROMPT:
        prompt = settings.SKILL_REVIEW_PROMPT
    else:
        prompt = DEFAULT_SKILL_REVIEW_PROMPT

    # Model
    bot_model = getattr(bot_row, "skill_review_model", None)
    model = bot_model if bot_model else (settings.SKILL_REVIEW_MODEL or None)

    # Model provider
    bot_provider = getattr(bot_row, "skill_review_model_provider_id", None)
    model_provider_id = bot_provider if bot_provider else (settings.SKILL_REVIEW_MODEL_PROVIDER_ID or None)

    # Target hour
    bot_target = getattr(bot_row, "skill_review_target_hour", None)
    target_hour = bot_target if bot_target is not None else settings.SKILL_REVIEW_TARGET_HOUR

    # Extra instructions
    extra_instructions = getattr(bot_row, "skill_review_extra_instructions", None)

    return JobConfig(
        enabled=enabled,
        interval_hours=interval_hours,
        prompt=prompt,
        only_if_active=only_if_active,
        model=model,
        model_provider_id=model_provider_id,
        target_hour=target_hour,
        extra_instructions=extra_instructions,
    )


# ---------------------------------------------------------------------------
# Legacy resolution helpers (direct attribute access for backward compat)
# ---------------------------------------------------------------------------

def resolve_enabled(bot_row: BotRow) -> bool:
    """Whether hygiene is enabled for this bot. Requires workspace-files scheme."""
    if bot_row.memory_scheme != "workspace-files":
        return False
    if bot_row.memory_hygiene_enabled is not None:
        return bot_row.memory_hygiene_enabled
    return settings.MEMORY_HYGIENE_ENABLED

def resolve_interval(bot_row: BotRow) -> int:
    if bot_row.memory_hygiene_interval_hours is not None:
        return bot_row.memory_hygiene_interval_hours
    return settings.MEMORY_HYGIENE_INTERVAL_HOURS

def resolve_only_if_active(bot_row: BotRow) -> bool:
    if bot_row.memory_hygiene_only_if_active is not None:
        return bot_row.memory_hygiene_only_if_active
    return settings.MEMORY_HYGIENE_ONLY_IF_ACTIVE

def resolve_prompt(bot_row: BotRow) -> str:
    if bot_row.memory_hygiene_prompt:
        return bot_row.memory_hygiene_prompt
    if settings.MEMORY_HYGIENE_PROMPT:
        return settings.MEMORY_HYGIENE_PROMPT
    return DEFAULT_MEMORY_HYGIENE_PROMPT

def resolve_model(bot_row: BotRow) -> str | None:
    val = getattr(bot_row, "memory_hygiene_model", None)
    if val:
        return val
    if settings.MEMORY_HYGIENE_MODEL:
        return settings.MEMORY_HYGIENE_MODEL
    return None

def resolve_model_provider_id(bot_row: BotRow) -> str | None:
    val = getattr(bot_row, "memory_hygiene_model_provider_id", None)
    if val:
        return val
    if settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID:
        return settings.MEMORY_HYGIENE_MODEL_PROVIDER_ID
    return None

def resolve_target_hour(bot_row: BotRow) -> int:
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

async def _build_working_set_snapshot(bot_id: str, db: AsyncSession) -> str:
    """Build a markdown snapshot of the bot's enrolled working set.

    Includes ALL enrolled skills (authored + catalog) in a unified list with
    source, age, per-bot fetch count, and global surface count.
    """
    from app.db.models import BotSkillEnrollment, Skill as SkillRow

    now_utc = datetime.now(timezone.utc)

    rows = (await db.execute(
        select(
            BotSkillEnrollment.skill_id,
            BotSkillEnrollment.source,
            BotSkillEnrollment.enrolled_at,
            BotSkillEnrollment.fetch_count,
            BotSkillEnrollment.last_fetched_at,
            BotSkillEnrollment.auto_inject_count,
            BotSkillEnrollment.last_auto_injected_at,
            SkillRow.name,
            SkillRow.surface_count,
            SkillRow.last_surfaced_at,
            SkillRow.created_at,
        )
        .join(SkillRow, SkillRow.id == BotSkillEnrollment.skill_id)
        .where(
            BotSkillEnrollment.bot_id == bot_id,
            SkillRow.archived_at.is_(None),
        )
        .order_by(BotSkillEnrollment.fetch_count.asc(), SkillRow.surface_count.asc())
    )).all()

    if not rows:
        return "## Working set\n\n_(no enrolled skills — nothing to prune)_"

    lines = [
        "## Working set",
        "",
        f"You have {len(rows)} enrolled skill(s). Listed by your fetch count (lowest first):",
        "",
        "**Reading the counts**:",
        "- `you fetched Nx` = how many times YOU called get_skill() for this skill (per-bot, most reliable signal)",
        "- `auto-injected Nx` = how many times the system pre-loaded this skill into your context (relevant to user query, counts as real usage)",
        "- `global Nx` = how many times ANY bot fetched this skill (fleet-wide, ambiguous)",
        "- `source=authored` = you wrote this skill; requires override reason to prune",
        "- Skills enrolled < 7 days ago are protected and require override reason to prune",
        "- A skill with 0 fetches but auto-injections is actively used — do NOT prune it",
        "",
    ]
    all_protected = True
    for r in rows:
        age_days = (now_utc - r.enrolled_at).days if r.enrolled_at else 0
        last_fetched = r.last_fetched_at.date().isoformat() if r.last_fetched_at else "never"
        enrolled = r.enrolled_at.date().isoformat() if r.enrolled_at else "?"
        protected = r.source == "authored" or age_days < 7
        if not protected:
            all_protected = False
        prot_tag = " **[protected]**" if protected else ""
        last_ai = r.last_auto_injected_at.date().isoformat() if r.last_auto_injected_at else "never"
        lines.append(
            f"- `{r.skill_id}` ({r.name}) — you fetched {r.fetch_count}x (last: {last_fetched}), "
            f"auto-injected {r.auto_inject_count}x (last: {last_ai}), "
            f"global {r.surface_count}x, enrolled {enrolled} ({age_days}d ago), "
            f"source={r.source}{prot_tag}"
        )

    if all_protected:
        lines.append("")
        lines.append(
            "**All skills are protected (enrolled < 14 days or authored). "
            "Skip pruning this cycle — focus on reflections and coverage gaps.**"
        )

    lines.append("")
    lines.append(
        "To prune: `prune_enrolled_skills(skill_ids=[...])`. "
        "Protected skills require `overrides={\"skill-id\": \"reason\"}`. "
        "Pruning authored skills archives them (reversible by admin)."
    )
    # Append auto-inject quality samples if there's injection history
    try:
        _inject_samples = await _build_inject_audit_samples(bot_id, db)
        if _inject_samples:
            lines.append("")
            lines.append(_inject_samples)
    except Exception:
        logger.debug("Failed to build inject audit samples for %s", bot_id, exc_info=True)

    return "\n".join(lines)


async def _build_inject_audit_samples(bot_id: str, db: AsyncSession) -> str:
    """Build sample turns for skills with 5+ auto-injects (last 14 days).

    Returns markdown showing the user messages that triggered each injection,
    so the hygiene bot can judge whether the skill was actually relevant.
    """
    from sqlalchemy import text as sa_text

    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=14)

    # Count auto-injects per skill (unnest the JSONB array)
    count_rows = (await db.execute(sa_text(
        "SELECT je.value::text AS skill_id, COUNT(*) AS n "
        "FROM trace_events te, jsonb_array_elements_text(te.data->'auto_injected') je "
        "WHERE te.event_type = 'skill_index' AND te.bot_id = :bot_id "
        "AND te.created_at >= :cutoff "
        "AND jsonb_array_length(COALESCE(te.data->'auto_injected', '[]'::jsonb)) > 0 "
        "GROUP BY je.value HAVING COUNT(*) >= 5 "
        "ORDER BY COUNT(*) DESC"
    ).bindparams(bot_id=bot_id, cutoff=cutoff))).all()

    if not count_rows:
        return ""

    lines = [
        "### Auto-inject quality samples (last 14 days)",
        "Review whether these skills were relevant to the conversations where they were injected.",
        "",
    ]

    for row in count_rows[:5]:  # cap at 5 skills
        skill_id = row.skill_id
        inject_count = row.n

        # Get 3 sample turns: find correlation_ids where this skill was injected,
        # then get the user message from those turns
        sample_rows = (await db.execute(sa_text(
            "SELECT DISTINCT ON (m.correlation_id) "
            "  LEFT(m.content, 120) AS user_msg "
            "FROM trace_events te "
            "JOIN messages m ON m.correlation_id = te.correlation_id "
            "WHERE te.event_type = 'skill_index' AND te.bot_id = :bot_id "
            "AND te.created_at >= :cutoff "
            "AND te.data->'auto_injected' ? :skill_id "
            "AND m.role = 'user' AND m.content IS NOT NULL "
            "ORDER BY m.correlation_id, m.created_at DESC "
            "LIMIT 3"
        ).bindparams(bot_id=bot_id, cutoff=cutoff, skill_id=skill_id))).all()

        lines.append(f"- `{skill_id}` (auto-injected {inject_count}x):")
        if sample_rows:
            for sr in sample_rows:
                msg = sr.user_msg.replace("\n", " ").strip()
                if len(msg) > 100:
                    msg = msg[:100] + "..."
                lines.append(f'  - "{msg}"')
        else:
            lines.append("  - (no message samples available)")
        lines.append("  → Were these relevant? If not, narrow triggers or prune.")
        lines.append("")

    return "\n".join(lines)


async def _build_channel_snapshot(bot_id: str, db: AsyncSession) -> str:
    """Build a markdown snapshot of the bot's channels with last activity.

    Injected into the hygiene prompt so the bot doesn't need to call
    list_channels() itself — less capable models skip that step.
    """
    from app.db.models import Channel, ChannelBotMember, Session as SessionRow
    from app.services.channels import bot_channel_filter

    now_utc = datetime.now(timezone.utc)

    # Get all channels this bot belongs to (primary + member)
    channels = (await db.execute(
        select(Channel.id, Channel.name, Channel.client_id, Channel.bot_id)
        .where(bot_channel_filter(bot_id))
        .order_by(Channel.name)
    )).all()

    if not channels:
        return "## Channels\n\n_(no channels found)_"

    # Get last activity per channel via most recent session
    ch_ids = [c.id for c in channels]
    activity_rows = (await db.execute(
        select(
            SessionRow.channel_id,
            func.max(SessionRow.last_active).label("last_active"),
        )
        .where(SessionRow.channel_id.in_(ch_ids))
        .group_by(SessionRow.channel_id)
    )).all()
    activity_by_ch = {r.channel_id: r.last_active for r in activity_rows}

    # Get user message counts in last 7 days per channel
    week_ago = now_utc - timedelta(days=7)
    msg_count_rows = (await db.execute(
        select(
            SessionRow.channel_id,
            func.count(Message.id).label("msg_count"),
        )
        .join(SessionRow, Message.session_id == SessionRow.id)
        .where(
            SessionRow.channel_id.in_(ch_ids),
            Message.role == "user",
            Message.created_at >= week_ago,
        )
        .group_by(SessionRow.channel_id)
    )).all()
    msg_counts = {r.channel_id: r.msg_count for r in msg_count_rows}

    lines = [
        "## Channels",
        "",
        f"You have {len(channels)} channel(s). Use `read_conversation_history(section=\"index\", channel_id=\"<id>\")` to review recent activity in any channel.",
        "",
    ]
    for ch in channels:
        label = ch.name or ch.client_id or "unnamed"
        role = "member" if str(ch.bot_id) != bot_id else "primary"
        last_active = activity_by_ch.get(ch.id)
        if last_active:
            if last_active.tzinfo is None:
                last_active = last_active.replace(tzinfo=timezone.utc)
            age_days = (now_utc - last_active).days
            active_str = f"{last_active.date().isoformat()} ({age_days}d ago)"
        else:
            active_str = "never"
        msgs_7d = msg_counts.get(ch.id, 0)
        lines.append(
            f"- **{label}** ({role}) — last active: {active_str}, "
            f"{msgs_7d} user msg(s) last 7d — `{ch.id}`"
        )

    return "\n".join(lines)


async def _build_recent_activity_snapshot(bot_id: str, db: AsyncSession) -> str:
    """Build a snapshot of recent user messages per channel.

    Gives the skill review bot concrete conversation content to base
    reflections on, instead of requiring tool calls to read_conversation_history.
    """
    from app.db.models import Channel, Session as SessionRow
    from app.services.channels import bot_channel_filter

    now_utc = datetime.now(timezone.utc)
    week_ago = now_utc - timedelta(days=7)

    channels = (await db.execute(
        select(Channel.id, Channel.name, Channel.client_id)
        .where(bot_channel_filter(bot_id))
        .order_by(Channel.name)
    )).all()

    if not channels:
        return "## Recent Activity\n\n_(no channels found)_"

    lines = [
        "## Recent Activity",
        "",
        "Recent user messages from the last 7 days (newest first, max 5 per channel):",
        "",
    ]
    for ch in channels:
        label = ch.name or ch.client_id or "unnamed"
        recent_msgs = (await db.execute(
            select(
                Message.content,
                Message.created_at,
            )
            .join(SessionRow, Message.session_id == SessionRow.id)
            .where(
                SessionRow.channel_id == ch.id,
                Message.role == "user",
                Message.content.is_not(None),
                Message.created_at >= week_ago,
            )
            .order_by(Message.created_at.desc())
            .limit(5)
        )).all()

        if recent_msgs:
            lines.append(f"**{label}**:")
            for msg in recent_msgs:
                preview = (msg.content or "")[:150].replace("\n", " ").strip()
                if len(msg.content or "") > 150:
                    preview += "..."
                ts = msg.created_at.strftime("%m-%d %H:%M") if msg.created_at else "?"
                lines.append(f"- [{ts}] {preview}")
        else:
            lines.append(f"**{label}** — _(no messages last 7d)_")
        lines.append("")

    return "\n".join(lines)


async def _build_previous_review_snapshot(bot_id: str, db: AsyncSession) -> str:
    """Fetch the previous completed skill review result for continuity.

    Gives the bot visibility into what the last review pass decided so it can
    avoid repeating observations and check whether reflections led to action.
    """
    prev = (await db.execute(
        select(Task.result, Task.completed_at)
        .where(
            Task.bot_id == bot_id,
            Task.task_type == "skill_review",
            Task.status == "completed",
        )
        .order_by(Task.completed_at.desc())
        .limit(1)
    )).first()

    if not prev or not prev.result:
        return ""

    date_str = prev.completed_at.date().isoformat() if prev.completed_at else "unknown"
    truncated = prev.result[:2000]
    if len(prev.result) > 2000:
        truncated += "\n\n_(truncated)_"
    return f"## Previous Skill Review ({date_str})\n\n{truncated}"


async def create_hygiene_task(
    bot_id: str,
    db: AsyncSession,
    *,
    job_type: JobType = "memory_hygiene",
    auto_commit: bool = True,
) -> uuid.UUID:
    """Create a hygiene/skill-review task for the given bot. Returns the task ID."""
    bot_row = await db.get(BotRow, bot_id)
    if not bot_row:
        raise ValueError(f"Bot not found: {bot_id}")

    meta = _JOB_META[job_type]
    cfg = resolve_config(bot_row, job_type)
    prompt = cfg.prompt

    # Append extra instructions if present
    if cfg.extra_instructions:
        prompt = f"{prompt}\n\n## Additional Instructions\n{cfg.extra_instructions}"

    # Append live snapshots — both job types get the channel snapshot
    try:
        ch_snapshot = await _build_channel_snapshot(bot_id, db)
        prompt = f"{prompt}\n\n{ch_snapshot}"
    except Exception:
        logger.warning("Failed to build channel snapshot for %s %s", job_type, bot_id, exc_info=True)

    # Only skill_review gets the working set, recent activity, and previous review
    if job_type == "skill_review":
        try:
            snapshot = await _build_working_set_snapshot(bot_id, db)
            prompt = f"{prompt}\n\n{snapshot}"
        except Exception:
            logger.warning("Failed to build working-set snapshot for %s %s", job_type, bot_id, exc_info=True)

        try:
            activity = await _build_recent_activity_snapshot(bot_id, db)
            prompt = f"{prompt}\n\n{activity}"
        except Exception:
            logger.warning("Failed to build activity snapshot for %s %s", job_type, bot_id, exc_info=True)

        try:
            prev_review = await _build_previous_review_snapshot(bot_id, db)
            if prev_review:
                prompt = f"{prompt}\n\n{prev_review}"
        except Exception:
            logger.warning("Failed to build previous review snapshot for %s %s", job_type, bot_id, exc_info=True)

    # Build execution_config with model overrides if set
    exec_cfg: dict | None = None
    model = cfg.model
    provider = cfg.model_provider_id
    # Auto-resolve provider from model when not explicitly set
    if model and not provider:
        from app.services.providers import resolve_provider_for_model
        provider = resolve_provider_for_model(model)
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
        title=f"{meta['task_title']}: {bot_id}",
        task_type=job_type,
        status="pending",
        run_at=datetime.now(timezone.utc),
        dispatch_type="none",
        execution_config=exec_cfg,
        channel_id=None,
        session_id=None,
        client_id=None,
    )
    db.add(task)
    if auto_commit:
        await db.commit()

    logger.info("Created %s task %s for bot %s", job_type, task.id, bot_id)
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
        Find the next occurrence of target_hour that is strictly in the future,
        then add a deterministic stagger offset (0-59 min).

    After a completed run (after_run=True):
        Find the next occurrence of target_hour that is strictly in the future,
        then add ``(days_between - 1)`` days, where ``days_between`` is
        ``interval_hours`` rounded to whole days (min 1).
    """
    tz = ZoneInfo(settings.TIMEZONE)
    now_local = now_utc.astimezone(tz)

    # Build candidate: today at target_hour in local time
    candidate = now_local.replace(hour=target_hour, minute=0, second=0, microsecond=0)

    # Advance candidate to the next target_hour occurrence strictly after now.
    while candidate <= now_local:
        candidate += timedelta(days=1)

    if after_run:
        days_between = max(1, round(interval_hours / 24))
        candidate += timedelta(days=days_between - 1)

    # Convert to UTC, add deterministic stagger
    candidate_utc = candidate.astimezone(timezone.utc)
    stagger = _stagger_offset_minutes(bot_id, interval_hours, target_mode=True)
    return candidate_utc + timedelta(minutes=stagger)


# ---------------------------------------------------------------------------
# Schedule bootstrap (called when hygiene is first enabled via admin API)
# ---------------------------------------------------------------------------

async def bootstrap_hygiene_schedule(
    bot_row: BotRow,
    db: AsyncSession,
    job_type: JobType = "memory_hygiene",
) -> None:
    """Set next run time when a job is enabled for the first time.

    Uses a deterministic stagger offset so bots with the same interval
    don't all fire at the same time.
    """
    meta = _JOB_META[job_type]
    cfg = resolve_config(bot_row, job_type)

    if cfg.target_hour >= 0:
        now_utc = datetime.now(timezone.utc)
        next_run = _next_target_run(
            bot_row.id, cfg.target_hour, cfg.interval_hours, now_utc, after_run=False,
        )
    else:
        offset = _stagger_offset_minutes(bot_row.id, cfg.interval_hours)
        next_run = datetime.now(timezone.utc) + timedelta(minutes=offset)

    setattr(bot_row, meta["col_next_run"], next_run)
    await db.commit()
    logger.info("Bootstrapped %s schedule for bot %s: next run at %s", job_type, bot_row.id, next_run)


# ---------------------------------------------------------------------------
# Compute next run (used by scheduler and recalc-on-change)
# ---------------------------------------------------------------------------

def _compute_next_run(
    bot_row: BotRow,
    now_utc: datetime,
    *,
    job_type: JobType = "memory_hygiene",
    after_run: bool = False,
) -> datetime:
    """Compute the next run time for a bot/job_type combination."""
    cfg = resolve_config(bot_row, job_type)

    if cfg.target_hour >= 0:
        return _next_target_run(
            bot_row.id, cfg.target_hour, cfg.interval_hours, now_utc, after_run=after_run,
        )
    return now_utc + timedelta(hours=cfg.interval_hours)


# ---------------------------------------------------------------------------
# Cross-job stagger (avoid running both jobs for same bot simultaneously)
# ---------------------------------------------------------------------------

def _cross_job_stagger(
    bot_row: BotRow,
    job_type: JobType,
    proposed: datetime,
) -> datetime:
    """If proposed run time is within 30 min of the other job, push forward 60 min."""
    other_meta = _JOB_META["skill_review" if job_type == "memory_hygiene" else "memory_hygiene"]
    other_next = getattr(bot_row, other_meta["col_next_run"], None)
    if other_next is None:
        return proposed

    # Ensure timezone-aware comparison
    if other_next.tzinfo is None:
        other_next = other_next.replace(tzinfo=timezone.utc)
    if proposed.tzinfo is None:
        proposed = proposed.replace(tzinfo=timezone.utc)

    diff = abs((proposed - other_next).total_seconds())
    if diff < 1800:  # 30 minutes
        logger.info(
            "Cross-job stagger: %s for bot %s pushed forward 60 min (was within %d min of %s)",
            job_type, bot_row.id, int(diff / 60),
            "skill_review" if job_type == "memory_hygiene" else "memory_hygiene",
        )
        return proposed + timedelta(minutes=60)
    return proposed


# ---------------------------------------------------------------------------
# Main scheduler — called from task_worker loop
# ---------------------------------------------------------------------------

async def check_memory_hygiene() -> None:
    """Check all workspace-files bots and create tasks for those that are due.

    Checks both memory_hygiene and skill_review job types.
    """
    from app.db.engine import async_session

    now = datetime.now(timezone.utc)

    async with async_session() as db:
        # Find bots with workspace-files memory scheme
        rows = (await db.execute(
            select(BotRow).where(BotRow.memory_scheme == "workspace-files")
        )).scalars().all()

        for bot_row in rows:
            for job_type in ("memory_hygiene", "skill_review"):
                try:
                    await _check_job_for_bot(bot_row, job_type, now, db)
                except Exception:
                    logger.exception("Error checking %s for bot %s", job_type, bot_row.id)


async def _check_job_for_bot(
    bot_row: BotRow,
    job_type: JobType,
    now: datetime,
    db: AsyncSession,
) -> None:
    """Check whether a specific job type is due for a bot and create the task if so."""
    meta = _JOB_META[job_type]
    cfg = resolve_config(bot_row, job_type)

    if not cfg.enabled:
        return

    next_run = getattr(bot_row, meta["col_next_run"])
    last_run = getattr(bot_row, meta["col_last_run"])

    # First-time bootstrap: stagger instead of running immediately
    if next_run is None:
        if cfg.target_hour >= 0:
            next_run = _next_target_run(
                bot_row.id, cfg.target_hour, cfg.interval_hours, now, after_run=False,
            )
        else:
            offset = _stagger_offset_minutes(bot_row.id, cfg.interval_hours)
            next_run = now + timedelta(minutes=offset)

        next_run = _cross_job_stagger(bot_row, job_type, next_run)
        setattr(bot_row, meta["col_next_run"], next_run)
        await db.commit()
        logger.info("Bootstrapped %s for bot %s: first run at %s", job_type, bot_row.id, next_run)
        return

    # Skip if not yet due
    if next_run > now:
        return

    # Activity check (if enabled)
    if cfg.only_if_active:
        since = last_run or (now - timedelta(hours=cfg.interval_hours))
        if not await _has_activity_since(bot_row.id, since, db):
            # No activity — advance schedule, record a skipped Task row
            skip_task = Task(
                id=uuid.uuid4(),
                bot_id=bot_row.id,
                prompt="",
                title=f"{meta['task_title']} skipped: {bot_row.id}",
                task_type=job_type,
                status="skipped",
                run_at=now,
                completed_at=now,
                result=f"No user messages across bot's channels since {since.isoformat()}",
                dispatch_type="none",
                channel_id=None,
                session_id=None,
                client_id=None,
            )
            db.add(skip_task)
            new_next = _compute_next_run(bot_row, now, job_type=job_type, after_run=True)
            new_next = _cross_job_stagger(bot_row, job_type, new_next)
            setattr(bot_row, meta["col_next_run"], new_next)
            await db.commit()
            logger.info("Skipped %s for bot %s: no activity since %s", job_type, bot_row.id, since)
            return

    # Dedup: check if there's already a pending/running task of this type
    existing = (await db.execute(
        select(func.count())
        .select_from(Task)
        .where(
            Task.bot_id == bot_row.id,
            Task.task_type == job_type,
            Task.status.in_(["pending", "running"]),
        )
    )).scalar() or 0
    if existing > 0:
        logger.debug("Skipped %s for bot %s: task already in progress", job_type, bot_row.id)
        return

    # Create the task + advance schedule atomically
    await create_hygiene_task(bot_row.id, db, job_type=job_type, auto_commit=False)
    setattr(bot_row, meta["col_last_run"], now)
    new_next = _compute_next_run(bot_row, now, job_type=job_type, after_run=True)
    new_next = _cross_job_stagger(bot_row, job_type, new_next)
    setattr(bot_row, meta["col_next_run"], new_next)
    await db.commit()

    logger.info("Scheduled %s for bot %s, next at %s", job_type, bot_row.id, new_next)
