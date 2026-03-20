"""Shared Jinja2 filters for admin HTML — datetimes in configured local timezone."""
from __future__ import annotations

import functools
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.config import settings


@functools.lru_cache(maxsize=1)
def _display_tz() -> ZoneInfo:
    return ZoneInfo(settings.TIMEZONE)


def _as_utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _twelve_hour(local: datetime, *, seconds: bool) -> str:
    hour = int(local.strftime("%I"))
    ap = local.strftime("%p").lower()
    if seconds:
        return f"{hour}:{local.strftime('%M:%S')} {ap}"
    return f"{hour}:{local.strftime('%M')} {ap}"


def format_admin_datetime(dt: datetime | None) -> str:
    """Full date + 12h time in TIMEZONE, e.g. 2026-03-20 3:04 pm (no zone label)."""
    if dt is None:
        return ""
    local = _as_utc_aware(dt).astimezone(_display_tz())
    return f"{local.strftime('%Y-%m-%d')} {_twelve_hour(local, seconds=False)}"


def format_admin_clock(dt: datetime | None) -> str:
    """12h time-only in TIMEZONE, e.g. 3:04:02 pm."""
    if dt is None:
        return ""
    local = _as_utc_aware(dt).astimezone(_display_tz())
    return _twelve_hour(local, seconds=True)


def install_admin_template_filters(env) -> None:
    env.filters["fmt_dt"] = format_admin_datetime
    env.filters["fmt_clock"] = format_admin_clock
