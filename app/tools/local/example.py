from datetime import datetime, timezone

from app.tools.registry import register
from app.config import settings
from zoneinfo import ZoneInfo


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



@register({
    "type": "function",
    "function": {
        "name": "get_current_local_time",
        "description": "Returns the current local time.",
        "parameters": {"type": "object", "properties": {}},
    },
})

async def get_current_local_time() -> str: 
    return datetime.now(ZoneInfo(settings.TIMEZONE)).strftime("%Y-%m-%d %I:%M:%S %p")
