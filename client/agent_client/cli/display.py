"""Display and formatting helpers for the CLI using Rich."""
import re
import uuid

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

console = Console()

_TOOL_DISPLAY_NAMES = {
    "web_search": "Searching the web",
    "fetch_url": "Reading webpage",
    "get_current_time": "Checking the time",
    "update_persona": "Updating persona",
    "search_channel_workspace": "Searching workspace",
    "search_channel_archive": "Searching archive",
    "get_skill": "Loading skill",
    "manage_capability": "Managing capability",
    "manage_workflow": "Managing workflow",
    "schedule_task": "Scheduling task",
    "client_action": None,
    "shell_exec": None,
}

_NOSPEECH_RE = re.compile(r"\[nospeech\](.*?)\[/nospeech\]", re.DOTALL)


def _clean_for_markdown(text: str) -> str:
    """Strip [nospeech] tags from text before Rich Markdown rendering."""
    return _NOSPEECH_RE.sub("", text)


class StreamDisplay:
    """Manages Rich Live display for streaming markdown responses."""

    def __init__(self):
        self._live: Live | None = None
        self._buffer: str = ""
        self._was_started: bool = False

    def start(self) -> None:
        self._buffer = ""
        self._was_started = True
        self._live = Live(Text(""), console=console, refresh_per_second=8)
        self._live.start()

    def update_markdown(self, text: str) -> None:
        self._buffer = text
        if self._live is not None:
            self._live.update(Markdown(_clean_for_markdown(text)))

    def pause(self) -> None:
        """Stop Live rendering (for interactive prompts). Buffer preserved."""
        if self._live is not None:
            self._live.stop()
            self._live = None

    def resume(self) -> None:
        """Restart Live rendering with current buffer (only if it was previously active)."""
        if not self._was_started:
            return
        self._live = Live(
            Markdown(_clean_for_markdown(self._buffer)) if self._buffer else Text(""),
            console=console,
            refresh_per_second=8,
        )
        self._live.start()

    def finish(self) -> None:
        """Stop Live and print final rendered markdown."""
        if self._live is not None:
            self._live.stop()
            self._live = None
        if self._buffer:
            console.print(Markdown(_clean_for_markdown(self._buffer)))
            console.print()

    @property
    def is_active(self) -> bool:
        return self._live is not None


def strip_silent(text: str) -> tuple[str, str, bool]:
    """Parse [nospeech]...[/nospeech] markers from response text.

    Returns (display_text, speakable_text, has_nospeech).
    """
    if "[nospeech]" not in text:
        return text, text, False
    speakable = _NOSPEECH_RE.sub("", text).strip()
    display = _NOSPEECH_RE.sub(lambda m: m.group(1), text)
    return display, speakable, True


def tool_status(tool_name: str) -> str | None:
    """Return a human-readable status string, or None to suppress display."""
    if tool_name in _TOOL_DISPLAY_NAMES:
        return _TOOL_DISPLAY_NAMES[tool_name]
    return f"Using {tool_name}"


def short_id(sid: uuid.UUID | str) -> str:
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


def print_status(msg: str) -> None:
    """Print a dim status message. Content is escaped to prevent markup injection."""
    from rich.markup import escape
    console.print(f"  [dim]{escape(msg)}[/dim]")


def print_warning(msg: str) -> None:
    """Print a yellow warning message. Content is escaped to prevent markup injection."""
    from rich.markup import escape
    console.print(f"  [yellow]{escape(msg)}[/yellow]")


def print_error(msg: str) -> None:
    """Print a red error message. Content is escaped to prevent markup injection."""
    from rich.markup import escape
    console.print(f"  [red]{escape(msg)}[/red]")


def make_prompt(bot_id: str, channel_id: str | None, model_override: str | None) -> str:
    """Build the REPL prompt string, safe from Rich markup injection."""
    parts = [bot_id]
    if channel_id:
        parts.append(f"ch:{short_id(channel_id)}")
    if model_override:
        parts.append(model_override)
    return f"[{' | '.join(parts)}] > "


def print_banner(bot_id: str, session_id: str, channel_id: str | None, tts: bool) -> None:
    """Print the startup banner panel."""
    from rich.markup import escape
    lines = [f"Bot: [bold]{escape(bot_id)}[/bold]  Session: [bold]{short_id(session_id)}[/bold]"]
    if channel_id:
        lines.append(f"Channel: [bold]{short_id(channel_id)}[/bold]")
    lines.append(f"TTS: {'on' if tts else 'off'}")
    text = Text.from_markup("  ".join(lines))
    console.print(Panel(text, title="Agent Chat", border_style="blue", expand=False))
    console.print("[dim]Type /help for commands.[/dim]\n")
