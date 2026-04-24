"""Standing Orders — bot-spawned durable work items rendered as native widgets.

A Standing Order is a ``core/standing_order_native`` ``WidgetInstance`` that
ticks on a schedule via the native-widget cron dispatcher (see
``spawn_due_native_widget_ticks``). Each tick runs one step of the declared
strategy, updates state, checks completion, and either reschedules or fires
the terminal path (chat message + channel event).

State shape stored in ``WidgetInstance.state``::

    {
      "goal":              str,      # human-readable, shown on tile + in posts
      "status":            str,      # running | paused | done | cancelled | failed
      "strategy":          str,      # poll_url | timer
      "strategy_args":     dict,     # strategy-specific config, validated at spawn
      "strategy_state":    dict,     # mutable strategy scratch (e.g. last response)
      "interval_seconds":  int,      # cadence for the next tick after this one
      "iterations":        int,      # how many ticks have fired
      "max_iterations":    int,      # hard cap from spawn
      "completion":        dict,     # {kind, ...kind-specific args}
      "log":               list,     # last 20 entries [{at, text}]
      "message_on_complete": str|None,
      "owning_bot_id":     str,
      "owning_channel_id": str,
      "created_at":        iso8601,
      "updated_at":        iso8601,
      "next_tick_at":      iso8601 | None,
      "last_tick_at":      iso8601 | None,
      "terminal_reason":   str | None,
    }

Completion kinds (explicit, no LLM judging)::

    after_n_iterations  {"n": int}
    state_field_equals  {"path": "strategy_state.status_code", "value": 200}
    deadline_passed     {"at": iso8601}

Strategies::

    poll_url   args: {url: str, expect_status: int|None, body_contains: str|None}
    timer      args: {}     # no work per tick; relies on deadline_passed completion

Caps::

    MAX_STANDING_ORDERS_PER_BOT = 5
    MAX_ITERATIONS_HARD_CAP = 1000
    MAX_TICK_WALL_SECONDS = 2.0
    MIN_INTERVAL_SECONDS = 10
"""
from __future__ import annotations

import asyncio
import copy
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.engine import async_session
from app.db.models import Channel, Message, WidgetInstance
from app.domain.errors import ValidationError

logger = logging.getLogger(__name__)


STANDING_ORDER_WIDGET_REF = "core/standing_order_native"

MAX_STANDING_ORDERS_PER_BOT = 5
MAX_ITERATIONS_HARD_CAP = 1000
MAX_TICK_WALL_SECONDS = 2.0
MIN_INTERVAL_SECONDS = 10
_LOG_RETAIN = 20

_STRATEGY_IDS = ("poll_url", "timer")
_COMPLETION_KINDS = ("after_n_iterations", "state_field_equals", "deadline_passed")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Strategy tick results
# ---------------------------------------------------------------------------


@dataclass
class TickResult:
    """What one strategy tick produced.

    ``state_patch`` is merged into ``state["strategy_state"]`` so strategies
    can stash their scratch without touching higher-level fields.
    ``log_entry`` is a short one-liner appended to the widget log; ``None``
    suppresses the log append for a trivial tick.
    """

    state_patch: dict[str, Any] = field(default_factory=dict)
    log_entry: str | None = None
    failed: bool = False
    failure_reason: str | None = None


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


async def _tick_poll_url(args: dict[str, Any]) -> TickResult:
    from app.services.url_safety import UnsafePublicURLError, assert_public_url

    url = str(args.get("url") or "").strip()
    if not url:
        return TickResult(failed=True, failure_reason="poll_url: missing url")

    try:
        await assert_public_url(url)
    except UnsafePublicURLError as exc:
        return TickResult(failed=True, failure_reason=f"poll_url: {exc}")
    except Exception as exc:  # noqa: BLE001
        return TickResult(failed=True, failure_reason=f"poll_url: url check failed: {exc}")

    expect_status = args.get("expect_status")
    body_contains = args.get("body_contains")

    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        return TickResult(
            state_patch={"last_status_code": None, "last_error": str(exc)},
            log_entry=f"poll error: {type(exc).__name__}",
        )

    status = resp.status_code
    body_head = resp.text[:400] if body_contains is not None else ""
    match_body = True if body_contains is None else (str(body_contains) in body_head)
    match_status = True if expect_status is None else (status == int(expect_status))

    return TickResult(
        state_patch={
            "last_status_code": status,
            "last_body_head": body_head,
            "last_matched_status": match_status,
            "last_matched_body": match_body,
            "last_polled_at": _iso(_now()),
            "last_error": None,
        },
        log_entry=f"GET {url} -> {status}",
    )


async def _tick_timer(_args: dict[str, Any]) -> TickResult:
    return TickResult(log_entry=None)


_STRATEGY_HANDLERS = {
    "poll_url": _tick_poll_url,
    "timer": _tick_timer,
}


# ---------------------------------------------------------------------------
# Completion evaluation (explicit, no LLM judging)
# ---------------------------------------------------------------------------


def _get_state_path(state: dict[str, Any], path: str) -> Any:
    cursor: Any = state
    for key in path.split("."):
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(key)
    return cursor


def evaluate_completion(state: dict[str, Any], completion: dict[str, Any]) -> tuple[bool, str | None]:
    """Return ``(terminal, reason)`` — no LLM call, no drift heuristics."""
    kind = str(completion.get("kind") or "")
    if kind == "after_n_iterations":
        n = int(completion.get("n") or 0)
        iterations = int(state.get("iterations") or 0)
        if iterations >= n:
            return True, f"reached {n} iterations"
        return False, None
    if kind == "state_field_equals":
        path = str(completion.get("path") or "")
        if not path:
            return False, None
        actual = _get_state_path(state, path)
        expected = completion.get("value")
        if actual == expected:
            return True, f"{path} == {expected!r}"
        return False, None
    if kind == "deadline_passed":
        at = _parse_iso(str(completion.get("at") or ""))
        if at is None:
            return False, None
        if _now() >= at:
            return True, f"deadline {completion.get('at')} passed"
        return False, None
    return False, None


# ---------------------------------------------------------------------------
# Spawn-time validation
# ---------------------------------------------------------------------------


def validate_strategy(strategy: str, strategy_args: dict[str, Any]) -> None:
    if strategy not in _STRATEGY_IDS:
        raise ValidationError(
            f"Unknown strategy {strategy!r} — must be one of {list(_STRATEGY_IDS)}",
        )
    if strategy == "poll_url":
        url = str(strategy_args.get("url") or "").strip()
        if not url:
            raise ValidationError("poll_url strategy requires 'url'")
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValidationError("poll_url 'url' must be http:// or https://")


def validate_completion(completion: dict[str, Any]) -> None:
    kind = str(completion.get("kind") or "")
    if kind not in _COMPLETION_KINDS:
        raise ValidationError(
            f"Unknown completion kind {kind!r} — must be one of {list(_COMPLETION_KINDS)}",
        )
    if kind == "after_n_iterations":
        n = completion.get("n")
        if not isinstance(n, int) or n <= 0:
            raise ValidationError("after_n_iterations requires integer 'n' > 0")
        if n > MAX_ITERATIONS_HARD_CAP:
            raise ValidationError(
                f"after_n_iterations 'n' must be <= {MAX_ITERATIONS_HARD_CAP}",
            )
    elif kind == "state_field_equals":
        path = completion.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValidationError("state_field_equals requires 'path'")
        if "value" not in completion:
            raise ValidationError("state_field_equals requires 'value'")
    elif kind == "deadline_passed":
        at = _parse_iso(str(completion.get("at") or ""))
        if at is None:
            raise ValidationError("deadline_passed requires ISO8601 'at'")


def build_initial_state(
    *,
    goal: str,
    strategy: str,
    strategy_args: dict[str, Any],
    interval_seconds: int,
    max_iterations: int,
    completion: dict[str, Any],
    message_on_complete: str | None,
    owning_bot_id: str,
    owning_channel_id: str,
) -> dict[str, Any]:
    now = _now()
    return {
        "goal": goal,
        "status": "running",
        "strategy": strategy,
        "strategy_args": copy.deepcopy(strategy_args),
        "strategy_state": {},
        "interval_seconds": interval_seconds,
        "iterations": 0,
        "max_iterations": max_iterations,
        "completion": copy.deepcopy(completion),
        "log": [],
        "message_on_complete": message_on_complete,
        "owning_bot_id": owning_bot_id,
        "owning_channel_id": owning_channel_id,
        "created_at": _iso(now),
        "updated_at": _iso(now),
        "next_tick_at": _iso(now + timedelta(seconds=interval_seconds)),
        "last_tick_at": None,
        "terminal_reason": None,
    }


# ---------------------------------------------------------------------------
# Cron tick handler — registered on the native widget spec
# ---------------------------------------------------------------------------


async def on_tick(db: AsyncSession, instance: WidgetInstance) -> None:
    """Run one tick for a standing-order instance.

    Skips if not ``running``. Runs the strategy with a wall-time cap. Mutates
    ``instance.state`` and flags it modified. On terminal state, posts the
    completion message and commits so the channel-message path sees a row.
    """
    state = copy.deepcopy(instance.state or {})
    if state.get("status") != "running":
        return
    strategy = str(state.get("strategy") or "")
    handler = _STRATEGY_HANDLERS.get(strategy)
    if handler is None:
        state["status"] = "failed"
        state["terminal_reason"] = f"unknown strategy {strategy!r}"
        state["updated_at"] = _iso(_now())
        instance.state = state
        flag_modified(instance, "state")
        return

    now = _now()
    strategy_args = state.get("strategy_args") or {}

    try:
        result = await asyncio.wait_for(handler(strategy_args), timeout=MAX_TICK_WALL_SECONDS)
    except asyncio.TimeoutError:
        result = TickResult(
            log_entry=f"tick exceeded {MAX_TICK_WALL_SECONDS}s wall time",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("standing_order tick failed (widget %s)", instance.id)
        result = TickResult(log_entry=f"tick raised {type(exc).__name__}: {exc}")

    state["iterations"] = int(state.get("iterations") or 0) + 1
    state["last_tick_at"] = _iso(now)

    strategy_state = dict(state.get("strategy_state") or {})
    strategy_state.update(result.state_patch or {})
    state["strategy_state"] = strategy_state

    if result.log_entry:
        log = list(state.get("log") or [])
        log.append({"at": _iso(now), "text": result.log_entry})
        state["log"] = log[-_LOG_RETAIN:]

    terminal_reason: str | None = None
    if result.failed:
        state["status"] = "failed"
        terminal_reason = result.failure_reason or "strategy reported failure"
    else:
        max_iters = int(state.get("max_iterations") or MAX_ITERATIONS_HARD_CAP)
        if state["iterations"] >= max_iters:
            state["status"] = "done"
            terminal_reason = f"reached max_iterations {max_iters}"
        else:
            terminal, reason = evaluate_completion(state, state.get("completion") or {})
            if terminal:
                state["status"] = "done"
                terminal_reason = reason

    if state["status"] == "running":
        state["next_tick_at"] = _iso(now + timedelta(seconds=int(state.get("interval_seconds") or 60)))
    else:
        state["next_tick_at"] = None
        state["terminal_reason"] = terminal_reason

    state["updated_at"] = _iso(now)

    instance.state = state
    flag_modified(instance, "state")

    if state["status"] in ("done", "failed"):
        await _emit_terminal(db, instance, state)


async def _emit_terminal(db: AsyncSession, instance: WidgetInstance, state: dict[str, Any]) -> None:
    """Post the completion chat message and publish a channel event."""
    channel_id_str = str(state.get("owning_channel_id") or "").strip()
    if not channel_id_str:
        return
    try:
        channel_uuid = uuid.UUID(channel_id_str)
    except ValueError:
        logger.warning("standing_order %s has invalid owning_channel_id", instance.id)
        return

    channel = await db.get(Channel, channel_uuid)
    if channel is None or channel.active_session_id is None:
        logger.warning(
            "standing_order %s cannot post message: channel %s missing or has no active session",
            instance.id,
            channel_uuid,
        )
        return

    status = state.get("status")
    goal = str(state.get("goal") or "")
    reason = state.get("terminal_reason") or ""
    if status == "done":
        message_on_complete = str(state.get("message_on_complete") or "").strip()
        content = message_on_complete or f"Standing order completed: {goal}"
        if reason and reason not in content:
            content += f" ({reason})"
    else:
        content = f"Standing order failed: {goal}"
        if reason:
            content += f" — {reason}"

    owning_bot_id = str(state.get("owning_bot_id") or "").strip() or None

    msg = Message(
        id=uuid.uuid4(),
        session_id=channel.active_session_id,
        role="assistant",
        content=content,
        metadata_={
            "standing_order_widget_instance_id": str(instance.id),
            "standing_order_status": status,
            "source_bot_id": owning_bot_id,
        },
        created_at=_now(),
    )
    db.add(msg)
    await db.flush()

    try:
        from app.services.channel_events import publish_message

        publish_message(str(channel_uuid), msg)
    except Exception:
        logger.exception(
            "standing_order %s: failed to publish completion message to channel bus",
            instance.id,
        )


# ---------------------------------------------------------------------------
# Scheduler tick — parallel to ``widget_cron.spawn_due_widget_crons``
# ---------------------------------------------------------------------------


async def spawn_due_native_widget_ticks() -> None:
    """Dispatch native-widget cron ticks whose ``next_tick_at`` has arrived.

    Parallel to ``app/services/widget_cron.py::spawn_due_widget_crons`` which
    dispatches HTML widget ``@on_cron`` handlers. This path serves native
    widgets whose ``NativeWidgetSpec.cron`` is declared. State shape is
    described in this module's docstring.
    """
    from app.services.native_app_widgets import get_native_widget_spec

    now = _now()
    async with async_session() as db:
        rows = (
            await db.execute(
                select(WidgetInstance).where(WidgetInstance.widget_kind == "native_app")
            )
        ).scalars().all()
        due_ids: list[uuid.UUID] = []
        for row in rows:
            spec = get_native_widget_spec(row.widget_ref)
            if spec is None or spec.cron is None:
                continue
            state = row.state or {}
            if state.get("status") != "running":
                continue
            next_tick_at = _parse_iso(state.get("next_tick_at"))
            if next_tick_at is None or next_tick_at > now:
                continue
            due_ids.append(row.id)

    for instance_id in due_ids:
        try:
            await _fire_native_tick(instance_id)
        except Exception:
            logger.exception("native widget tick failed (instance %s)", instance_id)


async def _fire_native_tick(instance_id: uuid.UUID) -> None:
    from app.services.native_app_widgets import get_native_widget_spec

    async with async_session() as db:
        instance = await db.get(WidgetInstance, instance_id)
        if instance is None or instance.widget_kind != "native_app":
            return
        spec = get_native_widget_spec(instance.widget_ref)
        if spec is None or spec.cron is None:
            return
        await spec.cron.handler(db, instance)
        await db.commit()


# ---------------------------------------------------------------------------
# Action dispatcher helpers (used by the NativeWidgetSpec action handlers)
# ---------------------------------------------------------------------------


def count_active_for_bot(db_rows: list[WidgetInstance], bot_id: str) -> int:
    count = 0
    for row in db_rows:
        if row.widget_kind != "native_app" or row.widget_ref != STANDING_ORDER_WIDGET_REF:
            continue
        state = row.state or {}
        if state.get("owning_bot_id") != bot_id:
            continue
        if state.get("status") == "running":
            count += 1
    return count


async def count_active_standing_orders_for_bot(
    db: AsyncSession, bot_id: str
) -> int:
    """Count standing orders where ``status == "running"`` owned by ``bot_id``."""
    rows = (
        await db.execute(
            select(WidgetInstance).where(
                WidgetInstance.widget_kind == "native_app",
                WidgetInstance.widget_ref == STANDING_ORDER_WIDGET_REF,
            )
        )
    ).scalars().all()
    return count_active_for_bot(list(rows), bot_id)


async def create_standing_order_instance(
    db: AsyncSession,
    *,
    initial_state: dict[str, Any],
) -> WidgetInstance:
    """Create a unique ``WidgetInstance`` for one Standing Order.

    Multiple Standing Orders can coexist on the same channel, so each one
    gets a synthetic ``scope_ref`` that's unique per instance. The pin it's
    attached to lives on the normal channel dashboard.
    """
    synthetic_scope_ref = f"standing_order/{uuid.uuid4()}"
    instance = WidgetInstance(
        widget_kind="native_app",
        widget_ref=STANDING_ORDER_WIDGET_REF,
        scope_kind="dashboard",
        scope_ref=synthetic_scope_ref,
        config={},
        state=initial_state,
    )
    db.add(instance)
    await db.flush()
    return instance
