"""Admin terminal — PTY-backed shell sessions for the in-app web terminal.

The terminal is admin-only by design; it's the equivalent of giving the
admin SSH access to the Spindrel container, exposed through the same web
session they're already authenticated to. See ``docs/guides/admin-terminal.md``.
"""
from app.services.terminal.session import (
    TerminalSession,
    TerminalSessionLimitError,
    close_session,
    create_session,
    get_session,
    is_disabled,
    start_idle_sweeper,
)

__all__ = [
    "TerminalSession",
    "TerminalSessionLimitError",
    "close_session",
    "create_session",
    "get_session",
    "is_disabled",
    "start_idle_sweeper",
]
