from datetime import datetime, timezone

from app.tools.registry import register


@register({
    "type": "function",
    "function": {
        "name": "get_current_time",
        "description": "Returns the current UTC time.",
        "parameters": {"type": "object", "properties": {}},
    },
})
async def get_current_time() -> str:
    return datetime.now(timezone.utc).isoformat()
