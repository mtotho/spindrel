"""Transform agent output and timestamps for Slack."""
import re
from datetime import datetime, timezone


def format_last_active(raw: str) -> str:
    """Turn an ISO timestamp into a short relative time for Slack."""
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - dt
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "just now"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        if days < 30:
            return f"{days}d ago"
        return dt.strftime("%b %d")
    except (ValueError, TypeError):
        return (raw or "")[:16]


def format_response_for_slack(response: str) -> str:
    if not response or not response.strip():
        return "_(no response)_"
    formatted = re.sub(
        r"\[silent\](.*?)\[/silent\]",
        lambda m: f"_🔇 {m.group(1).strip()}_",
        response,
        flags=re.DOTALL | re.IGNORECASE,
    )
    formatted = re.sub(r"\[/?silent\]", "", formatted, flags=re.IGNORECASE).strip()
    if not formatted:
        return "_(no response)_"
    return formatted
