"""Helpers for passive message injection metadata."""
from __future__ import annotations


def build_injected_message_metadata(
    *,
    role: str,
    source: str | None,
    bot_id: str | None,
) -> dict:
    """Return UI-safe metadata for an injected passive message.

    API message injection can write assistant-role rows without going through
    the normal turn persistence path. Stamp those rows with the owning bot so
    chat surfaces do not fall back to the generic "Bot" label.
    """
    metadata = {"source": source} if source else {}
    if role != "assistant" or not bot_id:
        return metadata

    display_name = bot_id
    try:
        from app.agent.bots import get_bot

        bot = get_bot(bot_id)
        display_name = bot.display_name or bot.name or bot_id
    except Exception:
        pass

    metadata.update(
        {
            "sender_type": "bot",
            "sender_id": f"bot:{bot_id}",
            "sender_display_name": display_name,
        }
    )
    return metadata
