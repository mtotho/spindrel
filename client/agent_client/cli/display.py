"""Display and formatting helpers for the CLI."""
import re
import uuid

_TOOL_DISPLAY_NAMES = {
    "web_search": "Searching the web",
    "fetch_url": "Reading webpage",
    "get_current_time": "Checking the time",
    "search_memories": "Searching memories",
    "save_memory": "Saving to memory",
    "upsert_knowledge": "Updating knowledge",
    "get_knowledge": "Getting knowledge",
    "search_knowledge": "Searching knowledge",
    "update_persona": "Updating persona",
    "client_action": None,
    "shell_exec": None,  # handled specially via tool_request
}

_SILENT_RE = re.compile(r"\[silent\](.*?)\[/silent\]", re.DOTALL)


def strip_silent(text: str) -> tuple[str, str, bool]:
    """Parse [silent]...[/silent] markers from response text.

    Returns (display_text, speakable_text, has_silent).
    - display_text: full text with markers stripped (shown in terminal)
    - speakable_text: only the non-silent portions (sent to TTS)
    - has_silent: whether any silent markers were found
    """
    if "[silent]" not in text:
        return text, text, False

    speakable = _SILENT_RE.sub("", text).strip()
    display = _SILENT_RE.sub(lambda m: f"\033[2m{m.group(1)}\033[0m", text)
    return display, speakable, True


def tool_status(tool_name: str) -> str | None:
    """Return a human-readable status string, or None to suppress display."""
    if tool_name in _TOOL_DISPLAY_NAMES:
        return _TOOL_DISPLAY_NAMES[tool_name]
    return f"Using {tool_name}"


def short_id(sid: uuid.UUID) -> str:
    return str(sid)[:6]


def format_last_active(raw: str) -> str:
    """Turn an ISO timestamp into a human-friendly relative time."""
    if not raw:
        return ""
    try:
        from datetime import datetime, timezone

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
        return raw[:16]
