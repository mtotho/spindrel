"""ISO 8601 canonicalization for widget primitives.

Widget primitives (``timeline``, anything else that takes a timestamp) speak
ISO 8601 UTC at their interface. Integration transforms receive native tool
output (often epoch seconds from Unix-style services like Frigate) and must
coerce on the way in.

This module is the one-call helper. Using it at the edge keeps the
primitive-layer contract strict — one canonical timestamp format, no
mixed-type fields, no "maybe epoch, maybe ISO, maybe datetime" ambiguity.

Example::

    from app.services.time_coercion import to_iso_z

    event = {
        "id": ev["id"],
        "start": to_iso_z(ev["start_time"]),   # epoch seconds → ISO Z
        "end":   to_iso_z(ev["end_time"]),
        "label": ev["label"],
    }
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Union

TimestampLike = Union[str, int, float, datetime, None]


# Epoch-ms threshold: anything ≥ this is treated as milliseconds.
# 10**12 seconds ≈ year 33658, so any "seconds" field above this is almost
# certainly milliseconds. Authors with genuinely far-future epoch-seconds
# timestamps can pass a ``datetime`` to disambiguate.
_EPOCH_MS_THRESHOLD = 10**12


def to_iso_z(value: TimestampLike) -> Optional[str]:
    """Coerce a timestamp-like value to an ISO 8601 UTC string with ``Z`` suffix.

    Accepts:
      - ``None`` → ``None`` (passthrough so callers can map over optional fields)
      - ``str`` → parsed as ISO 8601; naive strings are assumed UTC
      - ``int`` / ``float`` → epoch seconds if ``< 1e12``, epoch milliseconds otherwise
      - ``datetime`` → converted to UTC; naive datetimes are assumed UTC

    Returns ISO 8601 UTC with second precision plus ``Z`` suffix
    (``"2026-04-23T14:00:12Z"``). Raises ``ValueError`` for values that don't
    parse, rather than silently falling back — the primitive layer expects
    loud failures at transform time, not silent "unknown" timestamps at render.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, bool):
        # ``bool`` is an ``int`` subclass in Python — guard before numeric path.
        raise ValueError(f"cannot coerce bool {value!r} to timestamp")
    elif isinstance(value, (int, float)):
        if value != value:  # NaN check without importing math
            raise ValueError("cannot coerce NaN to timestamp")
        seconds = value / 1000.0 if abs(value) >= _EPOCH_MS_THRESHOLD else float(value)
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            raise ValueError("cannot coerce empty string to timestamp")
        # Python's ``fromisoformat`` accepts ``Z`` natively in 3.11+, but
        # normalize defensively so the helper works identically across
        # runtime versions in the support window.
        normalized = s.rstrip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise ValueError(f"cannot parse {value!r} as ISO 8601") from exc
    else:
        raise ValueError(
            f"unsupported timestamp type: {type(value).__name__} ({value!r})"
        )

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    # Drop microseconds for stable, readable output. Widgets don't care about
    # sub-second precision at the primitive layer; authors who need it can
    # bypass this helper and emit their own string.
    dt = dt.replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def to_iso_z_or_none(value: Any) -> Optional[str]:
    """Lenient variant: returns ``None`` instead of raising on bad input.

    Useful in bulk map operations over tool output where an occasional
    malformed row shouldn't fail the whole widget render. Prefer ``to_iso_z``
    at transform boundaries where loud failure is the right default.
    """
    try:
        return to_iso_z(value)
    except ValueError:
        return None
