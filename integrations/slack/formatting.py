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


def format_thinking_for_slack(text: str) -> str:
    """Format intermediate 'thinking' text so it's visually distinct from final responses.

    Uses Slack blockquote (``>``) with a thought-bubble prefix so the user can
    immediately tell this is the agent reasoning, not its answer.
    """
    if not text or not text.strip():
        return "> 💭 _thinking…_"
    lines = text.strip().splitlines()
    quoted = "\n".join(f"> {line}" for line in lines)
    return f"> 💭 *Thinking:*\n{quoted}"


def markdown_to_slack_mrkdwn(text: str) -> str:
    """Convert common Markdown formatting to Slack mrkdwn.

    Transforms (outside code blocks and inline code):
    - ``**bold**`` → ``*bold*``
    - ``~~strike~~`` → ``~strike~``
    - ``[text](url)`` → ``<url|text>``
    """
    if not text:
        return text

    # Protect fenced code blocks and inline code by replacing with placeholders.
    # We restore them after the transforms so code content is never modified.
    _placeholders: list[str] = []

    def _protect(m: re.Match) -> str:
        _placeholders.append(m.group(0))
        return f"\x00PH{len(_placeholders) - 1}\x00"

    protected = re.sub(r"```[\s\S]*?```", _protect, text)
    protected = re.sub(r"`[^`\n]+`", _protect, protected)

    # **bold** → *bold*
    protected = re.sub(r"\*\*(.+?)\*\*", r"*\1*", protected)
    # ~~strike~~ → ~strike~
    protected = re.sub(r"~~(.+?)~~", r"~\1~", protected)
    # [text](url) → <url|text>
    protected = re.sub(
        r"\[([^\]]+)\]\((https?://[^\)]+)\)", r"<\2|\1>", protected
    )

    # Restore protected code segments.
    for i, original in enumerate(_placeholders):
        protected = protected.replace(f"\x00PH{i}\x00", original, 1)

    return protected


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
    return markdown_to_slack_mrkdwn(formatted)


def _truncate(text: str, limit: int) -> str:
    """Truncate *text* to *limit* chars, breaking at a word boundary."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0] or text[:limit]
    return cut.rstrip() + "…"


# ---------------------------------------------------------------------------
# Slack message limits:
#   • text field: ~40,000 chars (but mrkdwn rendering breaks on long messages)
#   • Block Kit text block: 3,000 chars
#   • Max blocks per message: 50
# In practice, messages beyond ~3,500 chars can render incorrectly (truncated
# from the top, missing code blocks).  We split at safe boundaries.
# ---------------------------------------------------------------------------
SLACK_MSG_CHUNK_LIMIT = 3500


def split_for_slack(text: str, limit: int = SLACK_MSG_CHUNK_LIMIT) -> list[str]:
    """Split *text* into chunks of at most *limit* chars for Slack.

    Tries to break at blank-line boundaries first, then single newlines, and
    falls back to a hard cut.  Code-block fences (```) are re-opened/closed
    across chunks so rendering stays correct.
    """
    if not text or len(text) <= limit:
        return [text] if text else [""]

    chunks: list[str] = []
    remaining = text
    in_code_block = False  # track whether we're inside a ``` fence

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        # Find a good break point within the limit.
        segment = remaining[:limit]
        # Prefer breaking at a blank line.
        break_at = segment.rfind("\n\n")
        if break_at < limit // 4:
            # No good blank-line break — try a single newline.
            break_at = segment.rfind("\n")
        if break_at < limit // 4:
            # Hard cut as last resort.
            break_at = limit

        chunk = remaining[:break_at].rstrip()
        remaining = remaining[break_at:].lstrip("\n")

        # Track code fences in this chunk.
        fence_count = chunk.count("```")
        if in_code_block:
            # Re-open the code block that was split.
            chunk = "```\n" + chunk
        if (fence_count + (1 if in_code_block else 0)) % 2 == 1:
            # Odd fences → we're now inside an unclosed block.  Close it.
            chunk = chunk + "\n```"
            in_code_block = True
        else:
            in_code_block = False

        chunks.append(chunk)

    return chunks if chunks else [""]


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

    # Generic fallback — try to surface the most useful argument value so the
    # user can see at a glance what the tool is doing.
    _HINT_KEYS = ("query", "prompt", "url", "path", "content", "name", "search", "message", "input", "text")
    for key in _HINT_KEYS:
        val = parsed.get(key)
        if val and isinstance(val, str):
            hint = val.split("\n", 1)[0]
            return f"🔧 {tool} → {_truncate(hint, 80)}"
    # If no recognisable key, show the first string arg (if any).
    for val in parsed.values():
        if isinstance(val, str) and val.strip():
            hint = val.strip().split("\n", 1)[0]
            return f"🔧 {tool} → {_truncate(hint, 80)}"
    return f"🔧 _{tool}..._"
