"""Discord message -> agent /chat dispatch.

Phase F of the Integration Delivery refactor: the in-subprocess
``stream_chat`` long-poll path and ``DiscordStreamBuffer`` are gone.
The Discord subprocess just enqueues turns via ``submit_chat`` (POST
/chat → 202) and the main-process ``DiscordRenderer`` consumes the
channel-events bus to render the response. See
``integrations/discord/renderer.py``.
"""
import base64
import logging

import discord

from agent_client import ensure_channel, store_passive_message_http, submit_chat, cancel_session
from session_helpers import discord_client_id
from discord_settings import DISCORD_TOKEN, ensure_config_fresh, get_channel_config
from state import get_channel_state

logger = logging.getLogger(__name__)

TEXT_MIMES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/html",
    "application/json",
    "application/xml",
    "text/x-python",
    "application/x-yaml",
}
MAX_TEXT_FILE_BYTES = 32_000  # ~8k tokens


async def _process_discord_files(attachments: list[discord.Attachment], user: str = "") -> tuple[str, list[dict], list[dict]]:
    """Download Discord attachments: append text file bodies to the message; collect images for the API.

    Returns (text_parts_joined, vision_attachments, file_metadata_for_server).
    """
    text_parts: list[str] = []
    vision_attachments: list[dict] = []
    file_metadata: list[dict] = []
    for att in attachments or []:
        mime = att.content_type or ""
        name = att.filename or "attachment"
        size = att.size or 0
        try:
            data = await att.read()
        except Exception as e:
            text_parts.append(f"\n[Could not fetch {name}: {e}]")
            continue
        # posted_by must be None for user uploads so that persist_turn's orphan-
        # linking associates them with the user message (not the assistant message).
        file_metadata.append({
            "url": att.url,
            "filename": name,
            "mime_type": mime,
            "size_bytes": size,
            "posted_by": None,
            "file_data": base64.b64encode(data).decode("ascii"),
        })
        if any(mime.startswith(t) for t in TEXT_MIMES) or mime.startswith("text/"):
            raw = data[:MAX_TEXT_FILE_BYTES]
            content = raw.decode("utf-8", errors="replace")
            truncated = len(data) > MAX_TEXT_FILE_BYTES
            suffix = "\n[...truncated]" if truncated else ""
            text_parts.append(f"\n\n[Attached file: {name}]\n```\n{content}{suffix}\n```")
        elif mime.startswith("image/"):
            vision_attachments.append({
                "type": "image",
                "content": base64.b64encode(data).decode("ascii"),
                "mime_type": mime,
                "name": name,
            })
    return "".join(text_parts), vision_attachments, file_metadata


async def dispatch(
    message: discord.Message,
    *,
    mentioned: bool = False,
):
    """Main entry point for processing a Discord message."""
    await ensure_config_fresh()
    channel = message.channel
    user = str(message.author.id)
    text = (message.content or "").strip()
    channel_id = str(channel.id)

    config = get_channel_config(channel_id)
    state = get_channel_state(channel_id)
    bot_id = state["bot_id"] or config["bot_id"]
    client_id = discord_client_id(channel_id)

    # Ensure Channel row exists on the server
    await ensure_channel(client_id, bot_id)

    # Strip the bot mention from the text if present
    if mentioned and message.mentions:
        for m in message.mentions:
            text = text.replace(f"<@{m.id}>", "").replace(f"<@!{m.id}>", "").strip()

    # STOP intercept
    if text.upper() == "STOP":
        try:
            result = await cancel_session(client_id, bot_id)
            if result.get("cancelled") or result.get("queued_tasks_cancelled", 0) > 0:
                parts = []
                if result.get("cancelled"):
                    parts.append("active request cancelled")
                q = result.get("queued_tasks_cancelled", 0)
                if q:
                    parts.append(f"{q} queued message(s) cancelled")
                await channel.send(f"*Cancellation requested: {', '.join(parts)}.*")
            else:
                await channel.send("*Nothing running to cancel.*")
        except Exception:
            logger.exception("STOP cancel failed for channel %s", channel_id)
            await channel.send("*Failed to cancel \u2014 server may be unreachable.*")
        return

    appended, attachments, file_metadata = await _process_discord_files(
        message.attachments, user
    )

    if mentioned and not text and not appended and not attachments:
        text = "[@mention only, no user text \u2014 use channel context and respond.]"

    if not text and not appended and not attachments:
        return
    if not text and attachments and not appended:
        text = "(see attached image(s))"

    # Determine active vs passive
    is_bot_sender = message.author.bot
    is_passive = not mentioned and config["require_mention"] and not (is_bot_sender and config.get("allow_bot_messages"))

    msg_metadata = {
        "passive": is_passive,
        "include_in_memory": config["passive_memory"],
        "trigger_rag": mentioned or not config["require_mention"] or (is_bot_sender and config.get("allow_bot_messages")),
        "source": "discord",
        "sender_type": "bot" if is_bot_sender else "human",
        "sender_id": f"discord:{user}",
        "recipient_id": f"bot:{bot_id}" if mentioned else None,
    }

    full_message = f"[Discord channel:{channel_id} user:{message.author.display_name}] {text}{appended}"

    if is_passive:
        try:
            await store_passive_message_http(
                client_id=client_id,
                bot_id=bot_id,
                content=full_message,
                metadata=msg_metadata,
            )
        except Exception:
            logger.exception("Passive message storage failed for channel %s", channel_id)
        return

    # Phase F: enqueue the turn on the server (POST /chat → 202) and
    # let the main-process DiscordRenderer drive delivery via the bus.
    dispatch_config = {
        "channel_id": channel_id,
        "user_message_id": str(message.id),
        "token": DISCORD_TOKEN,
    }
    try:
        await submit_chat(
            message=full_message,
            bot_id=bot_id,
            client_id=client_id,
            attachments=attachments if attachments else None,
            file_metadata=file_metadata if file_metadata else None,
            dispatch_type="discord",
            dispatch_config=dispatch_config,
            msg_metadata=msg_metadata,
        )
    except Exception:
        logger.exception("submit_chat failed for Discord channel %s", channel_id)
        try:
            await channel.send(
                "*Failed to enqueue request \u2014 server may be unreachable.*"
            )
        except Exception:
            pass
        return

    # React with hourglass on the user's message so they know we got it.
    try:
        await message.add_reaction("\u23f3")
    except Exception:
        logger.debug("Failed to add hourglass reaction", exc_info=True)
