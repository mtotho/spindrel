"""Widget state-poll transforms for task tools.

Consumed by ``tasks.widgets.yaml`` -> ``schedule_task.state_poll.transform``.
Reshapes ``list_tasks`` detail output into a dict whose timestamp fields are
formatted in the server's local timezone so the template renders a human
string instead of a raw ISO value.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings

logger = logging.getLogger(__name__)

_TIMESTAMP_FIELDS = ("scheduled_at", "run_at", "completed_at", "created_at")


def _format_iso(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return value
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return value
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%d %H:%M")
    try:
        local = dt.astimezone(ZoneInfo(settings.TIMEZONE))
    except Exception:
        return dt.strftime("%Y-%m-%d %H:%M %Z")
    return local.strftime("%Y-%m-%d %H:%M %Z")


def task_detail(raw_result: str, widget_meta: dict) -> dict:
    """Parse a ``list_tasks`` detail JSON and prettify timestamp fields."""
    try:
        data = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError):
        logger.debug("task_detail: raw_result is not JSON")
        return {}
    if not isinstance(data, dict):
        return {}
    if "error" in data:
        # Preserve error so template can surface it, but don't format.
        return data
    for key in _TIMESTAMP_FIELDS:
        if key in data:
            data[key] = _format_iso(data.get(key))
    return data
