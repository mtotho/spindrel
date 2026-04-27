"""Durable JSONL log handler.

Writes one JSON object per log record to ``/var/log/spindrel/agent-server.log``
with rotation (50 MB x 10 files). Console handler from ``logging.basicConfig``
keeps writing the human-readable format; this is purely additive so the
daily health summary can sweep yesterday's evidence after a container restart.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOG_DIR = Path("/var/log/spindrel")
DEFAULT_LOG_FILE = "agent-server.log"
DEFAULT_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 10


class JsonlFormatter(logging.Formatter):
    """One JSON object per record, fields the summary parser cares about."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        payload: dict = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_handler: logging.Handler | None = None


def install_jsonl_log_handler(
    *,
    log_dir: Path | str | None = None,
    filename: str = DEFAULT_LOG_FILE,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> logging.Handler | None:
    """Install a rotating JSONL file handler on the root logger.

    Idempotent. Returns the handler, or None if the log directory could not
    be created (we don't want logging setup to fail server startup).
    """
    global _handler
    if _handler is not None:
        return _handler

    if log_dir is not None:
        target_dir = Path(log_dir)
    elif "SPINDREL_LOG_DIR" in os.environ:
        target_dir = Path(os.environ["SPINDREL_LOG_DIR"])
    else:
        target_dir = DEFAULT_LOG_DIR
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Volume not mounted (test envs / dev runs). Skip silently — the in-memory
        # ring buffer + console output still cover the same data.
        return None

    path = target_dir / filename
    try:
        handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
    except OSError:
        return None
    handler.setFormatter(JsonlFormatter())
    handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(handler)
    _handler = handler
    return handler


def get_log_dir() -> Path:
    """Resolve the active log directory at call time (env-aware)."""
    if "SPINDREL_LOG_DIR" in os.environ:
        return Path(os.environ["SPINDREL_LOG_DIR"])
    return DEFAULT_LOG_DIR


def get_log_path() -> Path:
    """Return the canonical durable log path (independent of whether the
    handler is installed — used by the summary parser to read the file)."""
    return get_log_dir() / DEFAULT_LOG_FILE


def get_handler() -> logging.Handler | None:
    return _handler


def _reset_for_tests() -> None:
    global _handler
    if _handler is not None:
        try:
            logging.getLogger().removeHandler(_handler)
            _handler.close()
        except Exception:
            pass
    _handler = None
