import logging
from app.db.engine import async_session
from app.db.models import BotPersona
from sqlalchemy import select

logger = logging.getLogger(__name__)


async def get_persona(bot_id: str) -> str | None:
    async with async_session() as db:
        result = await db.execute(select(BotPersona).where(BotPersona.bot_id == bot_id))
        row = result.scalar_one_or_none()
        return row.persona_layer if row else None


async def write_persona(bot_id: str, content: str) -> tuple[bool, str | None]:
    try:
        async with async_session() as db:
            await db.merge(BotPersona(bot_id=bot_id, persona_layer=content))
            await db.commit()
        logger.info("Updated persona for bot %s (%d chars)", bot_id, len(content))
        return (True, None)
    except Exception as e:
        logger.exception("Failed to write persona for bot %s", bot_id)
        return (False, str(e))