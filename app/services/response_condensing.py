"""Response condensing — condense verbose assistant responses at write-time."""
import logging
from uuid import UUID

from sqlalchemy import update

from app.config import settings
from app.db.engine import async_session
from app.db.models import Channel, Message

logger = logging.getLogger(__name__)

_DEFAULT_PROMPT = """\
Condense this assistant response to its essential information.
Preserve: specific values, decisions, code snippets, file paths, commands, action items.
Remove: verbose explanations, caveats, filler, redundant context.
Target: ~30% of original length."""


def _resolve_model(channel: Channel) -> str:
    """Resolve condensing model: channel > global > compaction chain."""
    if channel.response_condensing_model:
        return channel.response_condensing_model
    if settings.RESPONSE_CONDENSING_MODEL:
        return settings.RESPONSE_CONDENSING_MODEL
    if settings.CONTEXT_COMPRESSION_MODEL:
        return settings.CONTEXT_COMPRESSION_MODEL
    return settings.COMPACTION_MODEL


async def condense_response(
    message_id: UUID,
    content: str,
    channel: Channel,
    provider_id: str | None = None,
) -> str | None:
    """Condense an assistant response if above threshold.

    Returns the condensed text, or None if below threshold or on error.
    Stores the result on the Message row.
    """
    threshold = channel.response_condensing_threshold or settings.RESPONSE_CONDENSING_THRESHOLD
    if len(content) < threshold:
        return None

    model = _resolve_model(channel)

    # Prompt priority: channel > global setting > built-in default
    base_prompt = settings.RESPONSE_CONDENSING_PROMPT or _DEFAULT_PROMPT
    channel_prompt = channel.response_condensing_prompt or ""
    system_prompt = channel_prompt if channel_prompt else base_prompt

    prompt_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]

    try:
        from app.services.providers import get_llm_client
        response = await get_llm_client(provider_id).chat.completions.create(
            model=model,
            messages=prompt_messages,
            temperature=0.2,
            max_tokens=max(200, len(content) // 8),  # rough cap
        )
        condensed = response.choices[0].message.content or ""
        if not condensed.strip():
            return None

        # Store on the message row
        async with async_session() as db:
            await db.execute(
                update(Message)
                .where(Message.id == message_id)
                .values(condensed=condensed)
            )
            await db.commit()

        logger.info(
            "Condensed message %s: %d→%d chars (%.0f%%)",
            message_id, len(content), len(condensed),
            len(condensed) / len(content) * 100,
        )
        return condensed
    except Exception:
        logger.warning("Response condensing failed for message %s", message_id, exc_info=True)
        return None
