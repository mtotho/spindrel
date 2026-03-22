"""Media tools — read-only agent tools that surface *arr stack data.

Auto-discovered by app/tools/loader.py (integrations/*/tools/*.py pattern)
and attributed as source_integration="arr".

NOTE: These tools still use the core @register decorator because that is the
existing integration-tool discovery mechanism (see app/tools/loader.py L56-69).
If a dedicated integration-tool registration API is added later, migrate to it.
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from app.tools.registry import register

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[4] / "data" / "media"

_STALE_SECONDS = 2 * 3600  # 2 hours

# Patterns that indicate prompt injection in free-text fields
_INJECTION_PATTERNS = re.compile(
    r"(?i)"
    r"(?:ignore\s+(?:all\s+)?previous|you\s+are\s+now|"
    r"\[SYSTEM\]|disregard|new\s+instructions|"
    r"forget\s+(?:all\s+)?(?:your\s+)?instructions|"
    r"override\s+(?:your\s+)?(?:system|prompt))",
)


def _sanitize(text: str) -> str:
    """Strip prompt injection patterns from untrusted free-text."""
    if not text:
        return text
    cleaned = _INJECTION_PATTERNS.sub("[filtered]", text)
    # Truncate excessively long strings
    if len(cleaned) > 500:
        cleaned = cleaned[:500] + "..."
    return cleaned


def _load_file(filename: str) -> tuple[list | dict | None, str | None]:
    """Load a media JSON file. Returns (data, warning_or_none)."""
    path = _DATA_DIR / filename
    if not path.exists():
        return None, None
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return None, f"Error reading {filename}: {e}"

    warning = None
    fetched_at = raw.get("fetched_at")
    if fetched_at:
        try:
            ts = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            if age > _STALE_SECONDS:
                mins = int(age // 60)
                warning = f"Data is {mins} minutes old (fetched {fetched_at})"
        except (ValueError, TypeError):
            pass

    return raw.get("data", []), warning


def _no_data_msg(script_name: str) -> str:
    return f"No data yet — run integrations/arr/scripts/{script_name} first."


@register({
    "type": "function",
    "function": {
        "name": "media_today",
        "description": (
            "Show today's expected TV episodes and whether they've downloaded. "
            "Reads cached Sonarr calendar data."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
})
async def media_today() -> str:
    data, warning = _load_file("sonarr_today.json")
    if data is None and warning:
        return warning
    if data is None:
        return _no_data_msg("sonarr_today.sh")

    if not data:
        result = "No episodes expected today."
    else:
        lines = []
        for ep in data:
            series = _sanitize(ep.get("seriesTitle", "Unknown"))
            season = ep.get("seasonNumber", "?")
            episode = ep.get("episodeNumber", "?")
            title = _sanitize(ep.get("title", ""))
            has_file = ep.get("hasFile", False)
            status = "downloaded" if has_file else "missing"
            marker = "+" if has_file else "-"
            title_part = f' "{title}"' if title else ""
            lines.append(f"  {marker} {series} — S{season:02d}E{episode:02d}{title_part} — {status}")
        result = f"Today's Episodes ({len(data)}):\n" + "\n".join(lines)

    if warning:
        result = f"Warning: {warning}\n\n{result}"
    return result


@register({
    "type": "function",
    "function": {
        "name": "media_upcoming",
        "description": (
            "Show TV episodes airing in the next 7 days. "
            "Reads cached Sonarr calendar data."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
})
async def media_upcoming() -> str:
    data, warning = _load_file("sonarr_upcoming.json")
    if data is None and warning:
        return warning
    if data is None:
        return _no_data_msg("sonarr_upcoming.sh")

    if not data:
        result = "No upcoming episodes in the next 7 days."
    else:
        # Group by date
        by_date: dict[str, list[str]] = {}
        for ep in data:
            air_date = ep.get("airDateUtc", "")[:10] or "Unknown"
            series = _sanitize(ep.get("seriesTitle", "Unknown"))
            season = ep.get("seasonNumber", "?")
            episode = ep.get("episodeNumber", "?")
            title = _sanitize(ep.get("title", ""))
            has_file = ep.get("hasFile", False)
            marker = "+" if has_file else "-"
            title_part = f' "{title}"' if title else ""
            line = f"    {marker} {series} — S{season:02d}E{episode:02d}{title_part}"
            by_date.setdefault(air_date, []).append(line)

        lines = [f"Upcoming Episodes ({len(data)}):"]
        for date_str in sorted(by_date):
            lines.append(f"  {date_str}:")
            lines.extend(by_date[date_str])
        result = "\n".join(lines)

    if warning:
        result = f"Warning: {warning}\n\n{result}"
    return result


@register({
    "type": "function",
    "function": {
        "name": "media_downloads",
        "description": (
            "Show active torrent downloads and flag any stuck or stalled torrents. "
            "Reads cached qBittorrent data."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
})
async def media_downloads() -> str:
    data, warning = _load_file("qbit_status.json")
    if data is None and warning:
        return warning
    if data is None:
        return _no_data_msg("qbit_status.sh")

    if not data:
        result = "No active torrents."
    else:
        now_ts = datetime.now(timezone.utc).timestamp()
        active = []
        stuck = []
        for t in data:
            name = _sanitize(t.get("name", "Unknown"))
            state = t.get("state", "")
            progress = t.get("progress", 0)
            dlspeed = t.get("dlspeed", 0)
            added_on = t.get("added_on", 0)
            age_hours = (now_ts - added_on) / 3600 if added_on else 0

            pct = f"{progress * 100:.0f}%"

            if state == "stalledDL" or (state == "downloading" and dlspeed == 0 and age_hours > 24):
                stuck.append(f"    {name} — {state} — {pct} — {age_hours:.0f}h old")
            else:
                speed_str = _format_speed(dlspeed)
                eta = t.get("eta", 0)
                eta_str = _format_eta(eta)
                active.append(f"    {name} — {pct} — {speed_str} — {eta_str}")

        parts = []
        if active:
            parts.append(f"  Active ({len(active)}):\n" + "\n".join(active))
        if stuck:
            parts.append(f"  Stuck ({len(stuck)}):\n" + "\n".join(stuck))
        if not active and not stuck:
            parts.append("  All torrents completed or paused.")
        result = "Torrents:\n" + "\n".join(parts)

    if warning:
        result = f"Warning: {warning}\n\n{result}"
    return result


def _format_speed(bps: int) -> str:
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.1f} MB/s"
    if bps >= 1_000:
        return f"{bps / 1_000:.0f} KB/s"
    return f"{bps} B/s"


def _format_eta(seconds: int) -> str:
    if seconds <= 0 or seconds >= 8640000:
        return "ETA unknown"
    if seconds >= 3600:
        return f"ETA {seconds // 3600}h{(seconds % 3600) // 60}m"
    if seconds >= 60:
        return f"ETA {seconds // 60}m"
    return f"ETA {seconds}s"


@register({
    "type": "function",
    "function": {
        "name": "media_requests",
        "description": (
            "Show pending Jellyseerr media requests awaiting approval. "
            "Reads cached Jellyseerr data."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
})
async def media_requests() -> str:
    data, warning = _load_file("jellyseerr_pending.json")
    if data is None and warning:
        return warning
    if data is None:
        return _no_data_msg("jellyseerr_pending.sh")

    # Jellyseerr wraps results in a "results" key
    results = data if isinstance(data, list) else data.get("results", [])

    if not results:
        result = "No pending media requests."
    else:
        lines = [f"Pending Requests ({len(results)}):"]
        for req in results:
            media = req.get("media", {})
            media_type = req.get("type", media.get("mediaType", "unknown"))
            status = req.get("status", "?")
            # Try to get a title from the nested media info
            title = _sanitize(
                media.get("title")
                or media.get("name")
                or req.get("title")
                or req.get("name")
                or "Unknown"
            )
            requested_by = req.get("requestedBy", {}).get("displayName", "Unknown")
            lines.append(f"  - [{media_type}] {title} — status: {status} — by: {requested_by}")
        result = "\n".join(lines)

    if warning:
        result = f"Warning: {warning}\n\n{result}"
    return result


@register({
    "type": "function",
    "function": {
        "name": "media_status",
        "description": (
            "Combined media status: today's episodes, active downloads, and pending requests. "
            "Runs media_today, media_downloads, and media_requests together."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
})
async def media_status() -> str:
    sections = []
    sections.append("=== Today's Episodes ===\n" + await media_today())
    sections.append("=== Downloads ===\n" + await media_downloads())
    sections.append("=== Pending Requests ===\n" + await media_requests())
    return "\n\n".join(sections)
