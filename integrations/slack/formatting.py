"""Transform agent output and timestamps for Slack."""
from __future__ import annotations

import json
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


def _truncate(text: str, limit: int) -> str:
    """Truncate *text* to *limit* chars, breaking at a word boundary."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] or text[:limit]
    return cut.rstrip() + "…"


def format_tool_status(tool: str, raw_args: str | None = None) -> str:
    """Return a short Slack status string describing a tool invocation."""
    parsed: dict = {}
    if raw_args:
        try:
            val = json.loads(raw_args)
            if isinstance(val, dict):
                parsed = val
        except (json.JSONDecodeError, TypeError):
            pass

    if tool in ("exec_command", "exec_sandbox"):
        cmd = parsed.get("command")
        if cmd:
            return f"🔧 {tool} → `{_truncate(cmd, 100)}`"

    if tool == "delegate_to_harness":
        harness = parsed.get("harness", "harness")
        prompt = (parsed.get("prompt") or "").split("\n", 1)[0]
        if prompt:
            return f"🤖 {harness} → {_truncate(prompt, 80)}"
        return f"🤖 {harness}"

    if tool == "delegate_to_agent":
        bot_id = parsed.get("bot_id", "agent")
        prompt = (parsed.get("prompt") or "").split("\n", 1)[0]
        if prompt:
            return f"🤖 {bot_id} → {_truncate(prompt, 80)}"
        return f"🤖 {bot_id}"

    return f"🔧 _{tool}..._"
