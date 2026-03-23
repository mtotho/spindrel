"""JSONL logging for model elevation decisions.

Writes one JSON object per line to data/elevation_log.jsonl.
Async-safe via an asyncio lock on file appends.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from app.agent.elevation import ElevationDecision

logger = logging.getLogger(__name__)

_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
_LOG_PATH = os.path.join(_LOG_DIR, "elevation_log.jsonl")
_write_lock = asyncio.Lock()


async def log_elevation(
    decision: ElevationDecision,
    *,
    turn_id: uuid.UUID | None = None,
    bot_id: str = "",
    channel_id: uuid.UUID | None = None,
    elevation_enabled: bool = True,
    threshold: float = 0.0,
) -> str:
    """Write a pre-call elevation log entry. Returns the log entry ID for backfill."""
    entry_id = uuid.uuid4().hex
    entry: dict[str, Any] = {
        "id": entry_id,
        "turn_id": str(turn_id) if turn_id else None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bot_id": bot_id,
        "channel_id": str(channel_id) if channel_id else None,
        "elevation_enabled": elevation_enabled,
        "threshold": round(threshold, 4),
        "model_chosen": decision.model,
        "was_elevated": decision.was_elevated,
        "score": round(decision.score, 4),
        "rules_fired": decision.rules_fired,
        "signal_breakdown": decision.signal_breakdown,
        "tokens_used": None,
        "latency_ms": None,
    }
    await _append_entry(entry)
    return entry_id


async def backfill_elevation_log(
    entry_id: str,
    *,
    tokens_used: int | None = None,
    latency_ms: int | None = None,
    outcome: str | None = None,
    tool_call_count: int | None = None,
    total_iterations: int | None = None,
    turn_duration_ms: int | None = None,
    error: str | None = None,
) -> None:
    """Append a backfill record that associates outcome data with a prior log entry."""
    backfill: dict[str, Any] = {
        "id": entry_id,
        "backfill": True,
        "tokens_used": tokens_used,
        "latency_ms": latency_ms,
        "outcome": outcome,
        "tool_call_count": tool_call_count,
        "total_iterations": total_iterations,
        "turn_duration_ms": turn_duration_ms,
        "error": error,
    }
    await _append_entry(backfill)


async def _append_entry(entry: dict[str, Any]) -> None:
    """Append a single JSON line to the log file. Non-blocking, fire-and-forget safe."""
    try:
        line = json.dumps(entry, default=str) + "\n"
        async with _write_lock:
            os.makedirs(_LOG_DIR, exist_ok=True)
            with open(_LOG_PATH, "a") as f:
                f.write(line)
    except Exception:
        logger.warning("Failed to write elevation log entry", exc_info=True)
