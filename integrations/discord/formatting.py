"""Transform agent output for Discord.

Discord uses standard Markdown natively, so no markdown conversion is needed
(unlike Slack's mrkdwn). The main concern is the 2000-character message limit.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone


def format_last_active(raw: str) -> str:
    """Turn an ISO timestamp into a short relative time."""
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


def format_thinking_for_discord(text: str) -> str:
    """Format intermediate 'thinking' text so it's visually distinct from final responses.

    Uses Discord blockquote (``>``) with a thought-bubble prefix.
    """
    if not text or not text.strip():
        return "> :thought_balloon: *thinking...*"
    lines = text.strip().splitlines()
    quoted = "\n".join(f"> {line}" for line in lines)
    return f"> :thought_balloon: **Thinking:**\n{quoted}"


def format_response_for_discord(response: str) -> str:
    """Format agent response for Discord. Handles [silent] tags and empty responses."""
    if not response or not response.strip():
        return "*(no response)*"
    formatted = re.sub(
        r"\[silent\](.*?)\[/silent\]",
        lambda m: f"*:mute: {m.group(1).strip()}*",
        response,
        flags=re.DOTALL | re.IGNORECASE,
    )
    formatted = re.sub(r"\[/?silent\]", "", formatted, flags=re.IGNORECASE).strip()
    if not formatted:
        return "*(no response)*"
    return formatted


def _truncate(text: str, limit: int) -> str:
    """Truncate *text* to *limit* chars, breaking at a word boundary."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] or text[:limit]
    return cut.rstrip() + "\u2026"


# ---------------------------------------------------------------------------
# Discord message limit: 2000 characters per message.
# ---------------------------------------------------------------------------
DISCORD_MSG_CHUNK_LIMIT = 2000


def split_for_discord(text: str, limit: int = DISCORD_MSG_CHUNK_LIMIT) -> list[str]:
    """Split *text* into chunks of at most *limit* chars for Discord.

    Tries to break at blank-line boundaries first, then single newlines, and
    falls back to a hard cut. Code-block fences (```) are re-opened/closed
    across chunks so rendering stays correct.
    """
    if not text or len(text) <= limit:
        return [text] if text else [""]

    chunks: list[str] = []
    remaining = text
    in_code_block = False  # track whether we're inside a ``` fence

    _FENCE_OVERHEAD = 8  # "```\n" prefix + "\n```" suffix

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        # Reserve space for code fence re-opening/closing if we're mid-block
        effective_limit = limit - _FENCE_OVERHEAD if in_code_block else limit

        # Find a good break point within the limit.
        segment = remaining[:effective_limit]
        # Prefer breaking at a blank line.
        break_at = segment.rfind("\n\n")
        if break_at < effective_limit // 4:
            # No good blank-line break -- try a single newline.
            break_at = segment.rfind("\n")
        if break_at < effective_limit // 4:
            # Hard cut as last resort.
            break_at = effective_limit

        chunk = remaining[:break_at].rstrip()
        remaining = remaining[break_at:].lstrip("\n")

        # Track code fences in this chunk.
        fence_count = chunk.count("```")
        if in_code_block:
            # Re-open the code block that was split.
            chunk = "```\n" + chunk
        if (fence_count + (1 if in_code_block else 0)) % 2 == 1:
            # Odd fences -> we're now inside an unclosed block. Close it.
            chunk = chunk + "\n```"
            in_code_block = True
        else:
            in_code_block = False

        chunks.append(chunk)

    return chunks if chunks else [""]


def format_tool_status(tool: str, raw_args: str | None = None) -> str:
    """Return a short status string describing a tool invocation."""
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
            return f":wrench: {tool} \u2192 `{_truncate(cmd, 100)}`"

    if tool == "delegate_to_agent":
        bot_id = parsed.get("bot_id", "agent")
        prompt = (parsed.get("prompt") or "").split("\n", 1)[0]
        if prompt:
            return f":robot: {bot_id} \u2192 {_truncate(prompt, 80)}"
        return f":robot: {bot_id}"

    # Generic fallback
    _HINT_KEYS = ("query", "prompt", "url", "path", "content", "name", "search", "message", "input", "text")
    for key in _HINT_KEYS:
        val = parsed.get(key)
        if val and isinstance(val, str):
            hint = val.split("\n", 1)[0]
            return f":wrench: {tool} \u2192 {_truncate(hint, 80)}"
    for val in parsed.values():
        if isinstance(val, str) and val.strip():
            hint = val.strip().split("\n", 1)[0]
            return f":wrench: {tool} \u2192 {_truncate(hint, 80)}"
    return f":wrench: *{tool}...*"
