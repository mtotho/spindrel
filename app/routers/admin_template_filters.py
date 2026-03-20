"""Shared Jinja2 filters for admin HTML — datetimes in configured local timezone."""
from __future__ import annotations

import functools
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from markupsafe import Markup, escape

from app.config import settings

# Mirrors the regex in app/agent/tags.py
_TAG_RE = re.compile(r"(?<![<\w@])@((?:skill|knowledge|tool-pack|tool):)?([A-Za-z_][\w\-\.]*)")

_TAG_COLORS = {
    "skill": "bg-indigo-900 text-indigo-300",
    "tool": "bg-green-900 text-green-300",
    "tool-pack": "bg-green-900 text-green-300",
    "knowledge": "bg-purple-900 text-purple-300",
}


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


def highlight_prompt_tags(text: str | None) -> Markup:
    """Render @skill/tool/knowledge tags as colored inline badges; HTML-escape everything else."""
    if not text:
        return Markup("")
    parts: list[Markup] = []
    last = 0
    for m in _TAG_RE.finditer(text):
        parts.append(Markup(escape(text[last:m.start()])))
        prefix = m.group(1) or ""
        tag_type = prefix.rstrip(":") if prefix else "other"
        color = _TAG_COLORS.get(tag_type, "bg-gray-700 text-gray-300")
        parts.append(Markup(
            f'<span class="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-mono {color}">'
            f"{escape(m.group(0))}</span>"
        ))
        last = m.end()
    parts.append(Markup(escape(text[last:])))
    return Markup("").join(parts)


def install_admin_template_filters(env) -> None:
    env.filters["fmt_dt"] = format_admin_datetime
    env.filters["fmt_clock"] = format_admin_clock
    env.filters["highlight_tags"] = highlight_prompt_tags
