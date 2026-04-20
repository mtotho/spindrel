import json
from datetime import datetime, timezone

from app.tools.registry import register
from app.config import settings
from zoneinfo import ZoneInfo

_TIME_SCHEMA = {
    "type": "object",
    "properties": {
        "time": {"type": "string"},
        "timezone": {"type": "string"},
    },
}


@register({
    "type": "function",
    "function": {
        "name": "get_current_time",
        "description": "Returns the current UTC time.",
        "parameters": {"type": "object", "properties": {}},
    },
}, returns=_TIME_SCHEMA)
async def get_current_time() -> str:
    return json.dumps({"time": datetime.now(timezone.utc).isoformat(), "timezone": "UTC"}, ensure_ascii=False)


@register({
    "type": "function",
    "function": {
        "name": "get_current_local_time",
        "description": "Returns the current local time.",
        "parameters": {"type": "object", "properties": {}},
    },
}, returns=_TIME_SCHEMA)
async def get_current_local_time() -> str:
    tz = settings.TIMEZONE
    return json.dumps({"time": datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d %I:%M:%S %p"), "timezone": tz}, ensure_ascii=False)
