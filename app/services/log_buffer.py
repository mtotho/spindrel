"""In-memory ring buffer for Python log records.

Attaches as a logging.Handler so all server log output is captured
in a bounded deque.  The admin API can then query recent entries
with filters (level, logger name, text search, tail count).
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional


@dataclass(slots=True)
class LogEntry:
    timestamp: float
    level: str
    level_no: int
    logger: str
    message: str
    # Pre-formatted line (same format as console output)
    formatted: str


class RingBufferHandler(logging.Handler):
    """Logging handler that stores records in a bounded deque."""

    def __init__(self, capacity: int = 10_000, level: int = logging.DEBUG):
        super().__init__(level)
        self._buffer: deque[LogEntry] = deque(maxlen=capacity)
        self._lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = LogEntry(
                timestamp=record.created,
                level=record.levelname,
                level_no=record.levelno,
                logger=record.name,
                message=record.getMessage(),
                formatted=self.format(record),
            )
            with self._lock:
                self._buffer.append(entry)
        except Exception:
            self.handleError(record)

    def query(
        self,
        *,
        tail: int = 200,
        level: Optional[str] = None,
        logger: Optional[str] = None,
        search: Optional[str] = None,
        since: Optional[float] = None,
    ) -> list[LogEntry]:
        """Return filtered log entries (newest last)."""
        min_level_no = 0
        if level:
            min_level_no = getattr(logging, level.upper(), 0)

        search_lower = search.lower() if search else None

        with self._lock:
            entries = list(self._buffer)

        results: list[LogEntry] = []
        for e in entries:
            if min_level_no and e.level_no < min_level_no:
                continue
            if logger and not e.logger.startswith(logger):
                continue
            if search_lower and search_lower not in e.message.lower():
                continue
            if since and e.timestamp < since:
                continue
            results.append(e)

        # Return only the last `tail` entries
        if len(results) > tail:
            results = results[-tail:]
        return results


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_handler: Optional[RingBufferHandler] = None


def install(capacity: int = 10_000) -> RingBufferHandler:
    """Install the ring buffer handler on the root logger.

    Safe to call multiple times — returns the existing handler if
    already installed.
    """
    global _handler
    if _handler is not None:
        return _handler

    _handler = RingBufferHandler(capacity=capacity)
    # Use the same format as the console handler defined in main.py
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    _handler.setFormatter(fmt)
    logging.getLogger().addHandler(_handler)
    return _handler


def get_handler() -> Optional[RingBufferHandler]:
    return _handler
