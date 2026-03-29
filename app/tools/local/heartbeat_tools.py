"""Tools for inspecting heartbeat run history and dispatch."""
import json
import logging

from sqlalchemy import select

from app.agent.context import current_channel_id, current_dispatch_config, current_dispatch_type
from app.db.engine import async_session
from app.db.models import Task
from app.tools.registry import register

logger = logging.getLogger(__name__)


@register({
    "type": "function",
    "function": {
        "name": "get_last_heartbeat",
        "description": (
            "Get recent heartbeat results for the current channel. "
            "Returns the prompt, full result text, timestamps, and status. "
            "Use list_session_traces + get_trace with the session for deeper "
            "tool-call-level inspection."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of recent heartbeat results to return (default 1, max 10).",
                },
            },
            "required": [],
        },
    },
})
async def get_last_heartbeat(limit: int = 1) -> str:
    channel_id = current_channel_id.get()
    if not channel_id:
        return "No channel context available."

    limit = min(max(1, limit), 10)

    async with async_session() as db:
        stmt = (
            select(Task)
            .where(
                Task.channel_id == channel_id,
                Task.callback_config["source"].astext == "heartbeat",
                Task.status.in_(["complete", "failed"]),
            )
            .order_by(Task.completed_at.desc().nulls_last())
            .limit(limit)
        )
        tasks = list((await db.execute(stmt)).scalars().all())

    if not tasks:
        return "No completed heartbeat runs found for this channel."

    results = []
    for t in tasks:
        entry = {
            "task_id": str(t.id),
            "status": t.status,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            "prompt": t.prompt[:300] + "…" if len(t.prompt or "") > 300 else t.prompt,
            "result": t.result,
        }
        if t.error:
            entry["error"] = t.error
        results.append(entry)

    if len(results) == 1:
        return json.dumps(results[0], indent=2)
    return json.dumps(results, indent=2)


# Schema for the dynamically-injected channel-post tool.
# This is NOT listed in any bot's local_tools — it is injected at runtime
# by heartbeat.py when dispatch_mode == "optional".
POST_HEARTBEAT_TO_CHANNEL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "post_heartbeat_to_channel",
        "description": (
            "Post a message to the channel. Use this ONLY when you have something "
            "worth sharing with the channel. If nothing noteworthy came up during "
            "this heartbeat run, do NOT call this tool."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message text to post to the channel.",
                },
            },
            "required": ["message"],
        },
    },
}


@register(POST_HEARTBEAT_TO_CHANNEL_SCHEMA)
async def post_heartbeat_to_channel(message: str) -> str:
    from app.agent.context import current_bot_id
    dispatch_config = current_dispatch_config.get()
    dispatch_type = current_dispatch_type.get()
    bot_id = current_bot_id.get()

    if not dispatch_config or not dispatch_type:
        return "No dispatch context available — cannot post to channel."

    from app.agent import dispatchers
    dispatcher = dispatchers.get(dispatch_type)
    try:
        ok = await dispatcher.post_message(
            dispatch_config, message, bot_id=bot_id,
        )
        if ok:
            return "Message posted to channel successfully."
        return "Post dispatched (dispatcher returned no confirmation)."
    except Exception as exc:
        logger.warning("post_heartbeat_to_channel failed: %s", exc)
        return f"Failed to post to channel: {exc}"
