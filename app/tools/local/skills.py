"""get_skill tool — lets the agent fetch the full content of a configured skill on demand."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import update

from app.agent.context import current_bot_id
from app.tools.registry import register
from app.db.engine import async_session
from app.db.models import Skill as SkillRow

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "get_skill",
        "description": (
            "Retrieve the full content of a skill from the knowledge base by its ID. "
            "Use this when you need detailed information from one of your configured skills. "
            "The skill index in your system context shows which skills are available."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_id": {
                    "type": "string",
                    "description": "The skill ID to retrieve (e.g. 'arch_linux', 'cooking')",
                },
            },
            "required": ["skill_id"],
        },
    },
})
async def get_skill(skill_id: str) -> str:
    """Fetch the full content of a skill from DB."""
    from app.agent.context import current_channel_id
    bot_id = current_bot_id.get()
    channel_id = current_channel_id.get()

    # Bot-scoped skills (bots/{bot_id}/...) are private — only the owning bot can access
    if bot_id and skill_id.startswith("bots/") and not skill_id.startswith(f"bots/{bot_id}/"):
        return f"Skill '{skill_id}' is not configured for this bot."

    # Fetch from DB AND promote into the working set in the same session.
    # Doing both inside one `async with async_session()` ensures unit tests
    # that patch `async_session` see all the queries through the mock — no
    # leaked sessions against the real engine.
    async with async_session() as db:
        row = await db.get(SkillRow, skill_id)
        if not row:
            return f"Skill '{skill_id}' not found."
        if row.archived_at:
            return f"Skill '{skill_id}' is archived. Use manage_bot_skill(action='restore') to restore it."

        # Phase 3 working set: promote on successful fetch. Idempotent.
        # Capture the row attrs into locals BEFORE commit so the return below
        # never depends on `expire_on_commit=False` staying that way.
        row_name = row.name
        row_content = row.content
        if bot_id:
            try:
                from app.services.skill_enrollment import _upsert_ignore, _pick_stmt, invalidate_enrolled_cache
                pg_stmt, sqlite_stmt = _upsert_ignore({
                    "bot_id": bot_id,
                    "skill_id": skill_id,
                    "source": "fetched",
                })
                await db.execute(_pick_stmt(db, pg_stmt, sqlite_stmt))
                await db.commit()
                invalidate_enrolled_cache(bot_id)
            except Exception:
                # Promotion is best-effort but a failure here usually means the
                # schema is missing or the catalog is broken — surface as warning,
                # not debug, so prod issues are visible.
                logger.warning(
                    "Failed to promote %s into working set for bot %s",
                    skill_id, bot_id, exc_info=True,
                )

    # Track surfacing (fire-and-forget) — only counts actual LLM-initiated fetches
    asyncio.create_task(_increment_surface_count(skill_id, bot_id))

    return f"# {row_name}\n\n{row_content}"


_PRUNE_PROTECTION_DAYS = 7  # skills enrolled less than this many days ago are protected


@register({
    "type": "function",
    "function": {
        "name": "prune_enrolled_skills",
        "description": (
            "Remove skills from your persistent enrolled working set. The skills "
            "themselves stay in the catalog and can be re-fetched later via "
            "get_skill(). Use this in memory hygiene runs to drop skills you "
            "don't actively use. Bot-authored skills (source=authored) and skills "
            "enrolled less than 7 days ago require an explicit override reason."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Skill IDs to unenroll from this bot's working set",
                },
                "overrides": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": (
                        "Override reasons for protected skills. Map of skill_id to reason string. "
                        "Required for source=authored or recently-enrolled skills. "
                        "Example reasons: 'should be memory not skill', 'topic no longer relevant', "
                        "'merged into another skill'."
                    ),
                },
            },
            "required": ["skill_ids"],
        },
    },
})
async def prune_enrolled_skills(skill_ids: list[str], overrides: dict[str, str] | None = None) -> str:
    """Remove the listed skills from this bot's persistent enrollment.

    Protected skills (source=authored or enrolled < 7 days) require an override reason.
    Authored skills with an override are archived (soft-deleted) so auto-discovery
    doesn't re-enroll them.
    """
    bot_id = current_bot_id.get()
    if not bot_id:
        return "Cannot prune: no bot context."
    if not skill_ids:
        return "No skill IDs provided."

    overrides = overrides or {}

    from datetime import timedelta
    from sqlalchemy import select
    from app.db.models import BotSkillEnrollment
    from app.services.skill_enrollment import unenroll_many

    now = datetime.now(timezone.utc)
    protection_cutoff = now - timedelta(days=_PRUNE_PROTECTION_DAYS)

    # Look up enrollment details for all requested skill IDs
    async with async_session() as db:
        enrollment_rows = (await db.execute(
            select(
                BotSkillEnrollment.skill_id,
                BotSkillEnrollment.source,
                BotSkillEnrollment.enrolled_at,
            ).where(
                BotSkillEnrollment.bot_id == bot_id,
                BotSkillEnrollment.skill_id.in_(skill_ids),
            )
        )).all()

    enrollments_by_id = {r.skill_id: r for r in enrollment_rows}

    # Classify each skill ID
    allowed_ids: list[str] = []
    protected_ids: list[dict] = []  # [{skill_id, source, reason_needed, age_days}]
    override_ids: list[dict] = []   # [{skill_id, source, reason, age_days}]

    for sid in skill_ids:
        enrollment = enrollments_by_id.get(sid)
        if not enrollment:
            # Not enrolled — include anyway (unenroll_many is idempotent)
            allowed_ids.append(sid)
            continue

        is_authored = enrollment.source == "authored"
        enrolled_at = enrollment.enrolled_at
        # SQLite returns naive datetimes — make timezone-aware for comparison
        if enrolled_at.tzinfo is None:
            enrolled_at = enrolled_at.replace(tzinfo=timezone.utc)
        is_recent = enrolled_at > protection_cutoff
        age_days = (now - enrolled_at).days

        if is_authored or is_recent:
            reason = overrides.get(sid)
            if reason:
                override_ids.append({
                    "skill_id": sid,
                    "source": enrollment.source,
                    "reason": reason,
                    "age_days": age_days,
                })
            else:
                protection_reason = []
                if is_authored:
                    protection_reason.append("source=authored")
                if is_recent:
                    protection_reason.append(f"enrolled {age_days}d ago (<{_PRUNE_PROTECTION_DAYS}d)")
                protected_ids.append({
                    "skill_id": sid,
                    "source": enrollment.source,
                    "reason_needed": ", ".join(protection_reason),
                    "age_days": age_days,
                })
        else:
            allowed_ids.append(sid)

    # If there are protected skills without overrides, reject them
    if protected_ids:
        protected_list = "; ".join(
            f"{p['skill_id']} ({p['reason_needed']})" for p in protected_ids
        )
        msg = (
            f"Protected skills cannot be pruned without an override reason: {protected_list}. "
            f"To prune, call again with overrides={{\"skill-id\": \"reason\"}}. "
            f"Valid reasons: should be memory not skill, topic no longer relevant, "
            f"merged into another skill."
        )
        # Still prune the allowed ones
        if allowed_ids or override_ids:
            msg = f"Some skills are protected. {msg}"
        else:
            return msg

    # Process overrides: archive authored skills, then unenroll
    archived_ids: list[str] = []
    for ov in override_ids:
        sid = ov["skill_id"]
        if ov["source"] == "authored":
            # Archive the skill so auto-discovery doesn't re-enroll it
            try:
                async with async_session() as db:
                    skill_row = await db.get(SkillRow, sid)
                    if skill_row and not skill_row.archived_at:
                        skill_row.archived_at = now
                        await db.commit()
                        archived_ids.append(sid)
            except Exception:
                logger.warning("Failed to archive skill %s during prune override", sid, exc_info=True)
        allowed_ids.append(sid)

    # Record trace events for overrides
    if override_ids:
        try:
            from app.agent.context import current_correlation_id, current_session_id
            from app.agent.recording import _record_trace_event
            for ov in override_ids:
                asyncio.create_task(_record_trace_event(
                    correlation_id=current_correlation_id.get(),
                    session_id=current_session_id.get(),
                    bot_id=bot_id,
                    client_id=None,
                    event_type="skill_prune_override",
                    event_name=ov["skill_id"],
                    data={
                        "skill_id": ov["skill_id"],
                        "source": ov["source"],
                        "reason": ov["reason"],
                        "age_days": ov["age_days"],
                        "archived": ov["skill_id"] in archived_ids,
                    },
                ))
        except Exception:
            logger.debug("Failed to record prune override trace events", exc_info=True)

    # Unenroll the allowed + override IDs
    try:
        removed = await unenroll_many(bot_id, allowed_ids)
    except Exception as exc:
        logger.exception("prune_enrolled_skills failed for bot %s", bot_id)
        return f"Failed to prune enrollments: {exc}"

    parts: list[str] = []
    if removed > 0:
        parts.append(f"Pruned {removed} enrollment(s)")
    if archived_ids:
        parts.append(f"archived {len(archived_ids)} authored skill(s)")
    if protected_ids:
        parts.append(f"{len(protected_ids)} skill(s) blocked (need override reason)")

    if not parts:
        return f"No matching enrollments to remove ({len(skill_ids)} requested)."
    return ". ".join(parts) + "."


@register({
    "type": "function",
    "function": {
        "name": "get_skill_list",
        "description": (
            "List all available skills with their IDs, names, and descriptions. "
            "Use this to discover skills when the skill index in your context "
            "doesn't show what you need."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
})
async def get_skill_list() -> str:
    """Return the full flat index of all available skills."""
    from sqlalchemy import select

    bot_id = current_bot_id.get()

    async with async_session() as db:
        query = select(SkillRow.id, SkillRow.name, SkillRow.description, SkillRow.triggers).where(
            SkillRow.archived_at.is_(None),
        )
        # Exclude other bots' private skills
        if bot_id:
            query = query.where(
                ~SkillRow.id.like("bots/%") | SkillRow.id.like(f"bots/{bot_id}/%")
            )
        else:
            query = query.where(~SkillRow.id.like("bots/%"))
        rows = (await db.execute(query)).all()

    if not rows:
        return "No skills found."

    lines = []
    for r in rows:
        parts = [f"- {r.id}: {r.name}"]
        if r.description:
            parts.append(f" — {r.description}")
        if r.triggers:
            parts.append(f" [{', '.join(r.triggers)}]")
        lines.append("".join(parts))

    return f"All available skills ({len(lines)}):\n" + "\n".join(lines)



async def _increment_surface_count(skill_id: str, bot_id: str | None = None) -> None:
    """Increment surface_count and last_surfaced_at for a skill (fire-and-forget).

    Also increments per-enrollment fetch_count if bot_id is provided.
    """
    now = datetime.now(timezone.utc)
    try:
        async with async_session() as db:
            # Global skill surfacing
            await db.execute(
                update(SkillRow)
                .where(SkillRow.id == skill_id)
                .values(
                    last_surfaced_at=now,
                    surface_count=SkillRow.surface_count + 1,
                )
            )
            # Per-bot enrollment fetch tracking
            if bot_id:
                from app.db.models import BotSkillEnrollment
                await db.execute(
                    update(BotSkillEnrollment)
                    .where(
                        BotSkillEnrollment.bot_id == bot_id,
                        BotSkillEnrollment.skill_id == skill_id,
                    )
                    .values(
                        last_fetched_at=now,
                        fetch_count=BotSkillEnrollment.fetch_count + 1,
                    )
                )
            await db.commit()
    except Exception:
        logger.debug("Failed to update skill surfacing for %s", skill_id, exc_info=True)


async def _increment_auto_inject_count(skill_id: str, bot_id: str) -> None:
    """Increment auto_inject_count for a per-bot enrollment (fire-and-forget).

    Tracked separately from get_skill surfacings so hygiene can distinguish
    system-initiated auto-injects from bot-initiated fetches.
    Does NOT increment global Skill.surface_count.
    """
    now = datetime.now(timezone.utc)
    try:
        async with async_session() as db:
            from app.db.models import BotSkillEnrollment
            await db.execute(
                update(BotSkillEnrollment)
                .where(
                    BotSkillEnrollment.bot_id == bot_id,
                    BotSkillEnrollment.skill_id == skill_id,
                )
                .values(
                    last_auto_injected_at=now,
                    auto_inject_count=BotSkillEnrollment.auto_inject_count + 1,
                )
            )
            # Update global last_surfaced_at so Learning Center "Last Active"
            # reflects any activity, not just get_skill() calls.
            await db.execute(
                update(SkillRow)
                .where(SkillRow.id == skill_id)
                .values(last_surfaced_at=now)
            )
            await db.commit()
    except Exception:
        logger.debug("Failed to update auto-inject count for %s/%s", bot_id, skill_id, exc_info=True)
