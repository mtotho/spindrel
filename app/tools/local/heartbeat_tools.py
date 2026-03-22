"""Tools for inspecting heartbeat run history."""
import json

from sqlalchemy import select

from app.agent.context import current_channel_id
from app.db.engine import async_session
from app.db.models import Task
from app.tools.registry import register


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
