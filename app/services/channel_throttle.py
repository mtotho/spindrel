"""Per-channel agent run throttle — prevents bot-to-bot infinite loops.

Tracks timestamps of active (non-passive) agent runs per channel.
If a channel exceeds MAX_RUNS in WINDOW seconds, new requests are
rejected. This catches any loop regardless of integration:
  - Bot A → Slack → Bot B → Slack → Bot A
  - BB isFromMe echo storms
  - Heartbeat chains triggering each other

Human-initiated messages from the web UI are exempt (they have
sender_type="human" in msg_metadata).
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

# Defaults — can be overridden via config
_MAX_RUNS = 10          # max agent runs per channel in the window
_WINDOW = 300.0         # 5 minutes
_COOLDOWN_LOG_INTERVAL = 60.0  # log "still throttled" at most once per minute

# channel_id (str) → list of timestamps
_channel_runs: dict[str, list[float]] = defaultdict(list)
# channel_id → last time we logged a throttle warning (avoid log spam)
_last_throttle_log: dict[str, float] = {}


def configure(*, max_runs: int | None = None, window: float | None = None) -> None:
    """Override defaults (called from config/startup if needed)."""
    global _MAX_RUNS, _WINDOW
    if max_runs is not None:
        _MAX_RUNS = max_runs
    if window is not None:
        _WINDOW = window


def record_run(channel_id: str) -> None:
    """Record that an agent run started for this channel."""
    now = time.monotonic()
    _channel_runs[channel_id].append(now)
    _evict(channel_id, now)


def is_throttled(channel_id: str) -> bool:
    """Return True if the channel has exceeded the run rate limit.

    Does NOT record a new run — call record_run() separately when
    you actually start the agent.
    """
    now = time.monotonic()
    _evict(channel_id, now)
    recent = _channel_runs.get(channel_id, [])
    if len(recent) >= _MAX_RUNS:
        # Rate-limit the warning logs themselves
        last_log = _last_throttle_log.get(channel_id, 0)
        if now - last_log > _COOLDOWN_LOG_INTERVAL:
            logger.warning(
                "Channel %s throttled: %d agent runs in last %.0fs (max %d)",
                channel_id, len(recent), _WINDOW, _MAX_RUNS,
            )
            _last_throttle_log[channel_id] = now
        return True
    return False


def _evict(channel_id: str, now: float) -> None:
    """Remove timestamps outside the window."""
    cutoff = now - _WINDOW
    runs = _channel_runs.get(channel_id)
    if runs:
        _channel_runs[channel_id] = [ts for ts in runs if ts > cutoff]
        if not _channel_runs[channel_id]:
            del _channel_runs[channel_id]
            _last_throttle_log.pop(channel_id, None)


def status(channel_id: str) -> dict:
    """Return current throttle status for a channel (for diagnostics)."""
    now = time.monotonic()
    _evict(channel_id, now)
    recent = _channel_runs.get(channel_id, [])
    return {
        "channel_id": channel_id,
        "recent_runs": len(recent),
        "max_runs": _MAX_RUNS,
        "window_seconds": _WINDOW,
        "throttled": len(recent) >= _MAX_RUNS,
    }
