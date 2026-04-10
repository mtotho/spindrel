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
        # Channel-disabled skills are blocked even if the catalog has them.
        # Promotion to the working set is also blocked so disable stays effective.
        if channel_id is not None:
            from app.db.models import Channel as _ChannelRow
            ch = await db.get(_ChannelRow, channel_id)
            if ch is not None:
                disabled = set(getattr(ch, "skills_disabled", None) or [])
                if skill_id in disabled:
                    return f"Skill '{skill_id}' is disabled on this channel."

        row = await db.get(SkillRow, skill_id)
        if not row:
            return f"Skill '{skill_id}' not found."

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
    asyncio.create_task(_increment_surface_count(skill_id))

    return f"# {row_name}\n\n{row_content}"


@register({
    "type": "function",
    "function": {
        "name": "prune_enrolled_skills",
        "description": (
            "Remove skills from your persistent enrolled working set. The skills "
            "themselves stay in the catalog and can be re-fetched later via "
            "get_skill(). Use this in memory hygiene runs to drop skills you "
            "don't actively use — their slot in your working set will be freed "
            "and the semantic discovery layer will resurface them only when a "
            "user message is actually relevant. Does NOT delete the skill files "
            "or DB rows; for that use manage_bot_skill(action='delete')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Skill IDs to unenroll from this bot's working set",
                },
            },
            "required": ["skill_ids"],
        },
    },
})
async def prune_enrolled_skills(skill_ids: list[str]) -> str:
    """Remove the listed skills from this bot's persistent enrollment."""
    bot_id = current_bot_id.get()
    if not bot_id:
        return "Cannot prune: no bot context."
    if not skill_ids:
        return "No skill IDs provided."

    from app.services.skill_enrollment import unenroll_many

    try:
        removed = await unenroll_many(bot_id, skill_ids)
    except Exception as exc:
        logger.exception("prune_enrolled_skills failed for bot %s", bot_id)
        return f"Failed to prune enrollments: {exc}"

    if removed == 0:
        return f"No matching enrollments to remove ({len(skill_ids)} requested)."
    return f"Pruned {removed} enrollment(s) from your working set."


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
        query = select(SkillRow.id, SkillRow.name, SkillRow.description, SkillRow.triggers)
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



async def _increment_surface_count(skill_id: str) -> None:
    """Increment surface_count and last_surfaced_at for a skill (fire-and-forget)."""
    try:
        async with async_session() as db:
            await db.execute(
                update(SkillRow)
                .where(SkillRow.id == skill_id)
                .values(
                    last_surfaced_at=datetime.now(timezone.utc),
                    surface_count=SkillRow.surface_count + 1,
                )
            )
            await db.commit()
    except Exception:
        logger.debug("Failed to update skill surfacing for %s", skill_id, exc_info=True)
