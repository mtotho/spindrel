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
                return f"Skill '{skill_id}' is not configured for this bot."
        except Exception:
            pass  # bot not found — proceed without access check

    # Fetch from DB
    async with async_session() as db:
        row = await db.get(SkillRow, skill_id)
        if not row:
            return f"Skill '{skill_id}' not found."

    return f"# {row.name}\n\n{row.content}"
