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
    bot_id = current_bot_id.get()

    # Bot-scoped skills (bots/{bot_id}/...) are private — only the owning bot can access
    if bot_id and skill_id.startswith("bots/") and not skill_id.startswith(f"bots/{bot_id}/"):
        return f"Skill '{skill_id}' is not configured for this bot."

    # Fetch from DB
    async with async_session() as db:
        row = await db.get(SkillRow, skill_id)
        if not row:
            return f"Skill '{skill_id}' not found."

    # Track surfacing (fire-and-forget) — only counts actual LLM-initiated fetches
    asyncio.create_task(_increment_surface_count(skill_id))

    return f"# {row.name}\n\n{row.content}"


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
