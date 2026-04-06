"""Tool for invoking member bots mid-turn in multi-bot channels."""
import asyncio
import json
import logging
import uuid

from app.agent.context import (
    current_bot_id,
    current_channel_id,
    current_session_id,
    current_invoked_member_bots,
)
from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "invoke_member_bot",
        "description": (
            "Invoke a member bot to respond in this channel. The bot starts "
            "immediately and streams its response in parallel with yours. Use "
            "this when you want another bot's expertise without waiting for "
            "your response to finish."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "bot_id": {
                    "type": "string",
                    "description": "The bot_id of the member bot to invoke.",
                },
                "message": {
                    "type": "string",
                    "description": "Brief context or instruction for the member bot (optional).",
                },
            },
            "required": ["bot_id"],
        },
    },
})
async def invoke_member_bot(bot_id: str, message: str = "") -> str:
    channel_id = current_channel_id.get()
    session_id = current_session_id.get()
    my_bot_id = current_bot_id.get()

    if not channel_id or not session_id:
        return json.dumps({"error": "This tool can only be used in a channel context."})

    if bot_id == my_bot_id:
        return json.dumps({"error": "Cannot invoke yourself."})

    # Guard against double-invocation (LLM calling tool twice for same bot)
    invoked = current_invoked_member_bots.get() or set()
    if bot_id in invoked:
        return json.dumps({
            "status": "already_invoked",
            "message": f"@{bot_id} was already invoked this turn.",
        })

    # Validate bot exists and is a member of this channel
    from app.agent.bots import get_bot
    try:
        target_bot = get_bot(bot_id)
    except Exception:
        return json.dumps({"error": f"Bot '{bot_id}' not found."})

    from app.db.engine import async_session as _async_session
    from app.db.models import Channel, ChannelBotMember
    from sqlalchemy import select

    async with _async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            return json.dumps({"error": "Channel not found."})

        # Check if target is the primary bot or a member bot
        is_primary = channel.bot_id == bot_id
        member_config = {}
        if not is_primary:
            row = (await db.execute(
                select(ChannelBotMember).where(
                    ChannelBotMember.channel_id == channel_id,
                    ChannelBotMember.bot_id == bot_id,
                )
            )).scalar_one_or_none()
            if not row:
                return json.dumps({"error": f"Bot '{bot_id}' is not a member of this channel."})
            member_config = row.config or {}

    # Snapshot the current conversation from the session
    from app.services.sessions import load_or_create
    import copy

    async with _async_session() as db:
        _, messages = await load_or_create(
            db, session_id, "member-mention", my_bot_id,
            channel_id=channel_id,
            preserve_metadata=True,
        )
    messages_snapshot = copy.deepcopy(messages)

    # Track this bot as invoked so post-completion @-mention scan skips it
    invoked = set(current_invoked_member_bots.get() or ())  # new set — don't mutate in-place
    invoked.add(bot_id)
    current_invoked_member_bots.set(invoked)

    # Fire the member bot reply as a background task
    from app.routers.chat import _run_member_bot_reply, _background_tasks

    stream_id = str(uuid.uuid4())
    task = asyncio.create_task(
        _run_member_bot_reply(
            channel_id, session_id, bot_id, member_config,
            my_bot_id,
            _depth=1,
            messages_snapshot=messages_snapshot,
            stream_id=stream_id,
            invocation_message=message,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    bot_name = target_bot.name if target_bot else bot_id
    return json.dumps({
        "status": "ok",
        "message": f"Invoked @{bot_name}. They are responding in the channel now.",
    })
