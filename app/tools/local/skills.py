"""get_skill tool — lets the agent fetch the full content of a configured skill on demand."""
import logging

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

    # Virtual skill: api_reference — generated from bot's API key scopes
    if skill_id == "api_reference":
        if bot_id:
            try:
                from app.agent.bots import get_bot
                bot = get_bot(bot_id)
                if bot.api_permissions:
                    from app.services.api_keys import generate_api_docs
                    return generate_api_docs(bot.api_permissions)
            except Exception:
                logger.warning("Failed to generate api_reference skill for bot %s", bot_id, exc_info=True)
        return "No API permissions configured for this bot."

    # Validate that this bot has access to this skill
    if bot_id:
        try:
            from app.agent.bots import get_bot
            bot = get_bot(bot_id)
            if bot.skills and skill_id not in bot.skill_ids:
                # Check ephemeral @-tagged skills first
                from app.agent.context import current_ephemeral_skills
                if skill_id in (current_ephemeral_skills.get() or []):
                    pass  # tagged skill — allow access
                else:
                    # Check workspace DB skills and channel skills_extra
                    _allowed = await _check_extra_skill_access(bot, skill_id)
                    if not _allowed:
                        return f"Skill '{skill_id}' is not configured for this bot."
        except Exception:
            pass  # bot not found — proceed without access check

    # Fetch from DB
    async with async_session() as db:
        row = await db.get(SkillRow, skill_id)
        if not row:
            return f"Skill '{skill_id}' not found."

    return f"# {row.name}\n\n{row.content}"


async def _check_extra_skill_access(bot, skill_id: str) -> bool:
    """Check if skill_id is allowed via workspace DB skills or channel skills_extra."""
    # Check workspace DB skills
    if bot.shared_workspace_id:
        try:
            import uuid as _uuid
            from app.db.models import SharedWorkspace
            async with async_session() as db:
                ws_row = await db.get(SharedWorkspace, _uuid.UUID(bot.shared_workspace_id))
            if ws_row and ws_row.skills:
                if any(
                    (e["id"] if isinstance(e, dict) else e) == skill_id
                    for e in ws_row.skills
                ):
                    return True
        except Exception:
            pass

    # Check channel skills_extra
    try:
        from app.agent.context import current_channel_id
        _ch_id = current_channel_id.get()
        if _ch_id:
            from app.db.models import Channel
            async with async_session() as db:
                ch = await db.get(Channel, _ch_id)
            if ch and ch.skills_extra:
                if any(
                    (e["id"] if isinstance(e, dict) else e) == skill_id
                    for e in ch.skills_extra
                ):
                    return True
    except Exception:
        pass

    return False
