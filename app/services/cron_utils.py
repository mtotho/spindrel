"""Cron-expression helpers for per-subscription schedules.

Thin wrapper over ``croniter`` that keeps the validation + next-fire
logic in one place so routers and the task worker share semantics.
"""
from __future__ import annotations

from datetime import datetime, timezone


def validate_cron(expr: str) -> None:
    """Raise ``ValueError`` if the expression is not a valid 5-field cron."""
    from croniter import croniter

    if not isinstance(expr, str) or not expr.strip():
        raise ValueError("cron expression must be a non-empty string")
    # 5-field classic cron; reject seconds/extended variants to keep the
    # UI story simple and consistent across backend and client preview.
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(
            f"cron expression must have 5 fields (minute hour dom month dow), got {len(parts)}"
        )
    if not croniter.is_valid(expr):
        raise ValueError(f"invalid cron expression: {expr!r}")


def next_fire_at(expr: str, base: datetime | None = None) -> datetime:
    """Return the next datetime (UTC, tz-aware) a cron schedule fires after ``base``."""
    from croniter import croniter

    if base is None:
        base = datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    itr = croniter(expr, base)
    nxt = itr.get_next(datetime)
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=timezone.utc)
    return nxt


def next_n_fires(expr: str, base: datetime | None = None, n: int = 3) -> list[datetime]:
    """Return the next ``n`` fire times (for UI preview)."""
    from croniter import croniter

    if base is None:
        base = datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    itr = croniter(expr, base)
    out: list[datetime] = []
    for _ in range(n):
        nxt = itr.get_next(datetime)
        if nxt.tzinfo is None:
            nxt = nxt.replace(tzinfo=timezone.utc)
        out.append(nxt)
    return out
