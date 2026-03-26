import logging
from app.db.engine import async_session
from app.db.models import BotPersona
from sqlalchemy import select

logger = logging.getLogger(__name__)


def resolve_workspace_persona(workspace_id: str, bot_id: str) -> str | None:
    """Read bots/{bot_id}/persona.md from workspace. Returns content or None."""
    from app.services.shared_workspace import shared_workspace_service, SharedWorkspaceError

    try:
        result = shared_workspace_service.read_file(workspace_id, f"bots/{bot_id}/persona.md")
        return result["content"]
    except (SharedWorkspaceError, OSError):
        return None


async def get_persona(bot_id: str, workspace_id: str | None = None) -> str | None:
    if workspace_id:
        ws_persona = resolve_workspace_persona(workspace_id, bot_id)
        if ws_persona is not None:
            return ws_persona
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

async def edit_persona(bot_id: str, old_text: str, new_text: str) -> tuple[bool, str | None]:
    """Find-and-replace within the persona layer."""
    try:
        async with async_session() as db:
            existing = await db.execute(select(BotPersona).where(BotPersona.bot_id == bot_id))
            row = existing.scalar_one_or_none()
            if not row or not row.persona_layer:
                return (False, "Persona not found.")
            if old_text not in row.persona_layer:
                return (False, "old_text not found in persona. Review the [PERSONA] block in your context to see current content.")
            row.persona_layer = row.persona_layer.replace(old_text, new_text, 1)
            await db.commit()
            logger.info("Edited persona for bot %s (replaced %d chars)", bot_id, len(old_text))
            return (True, None)
    except Exception as e:
        logger.exception("Failed to edit persona for bot %s", bot_id)
        return (False, str(e))


async def append_to_persona(bot_id: str, content: str) -> tuple[bool, str | None]:
    # Validate that we have something to append
    if not content or not content.strip():
        return (False, "No content to append to persona.")
    try:
        async with async_session() as db:
            existing = await db.execute(select(BotPersona).where(BotPersona.bot_id == bot_id))
            row = existing.scalar_one_or_none()
            if not row:
                return (False, "Persona not found.")
            row.persona_layer = (row.persona_layer or "") + content
            await db.commit()
            logger.info("Appended to persona for bot %s (%d chars appended)", bot_id, len(content))
            return (True, None)
    except Exception as e:
        logger.exception("Failed to append to persona for bot %s", bot_id)
        return (False, str(e))