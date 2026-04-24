"""Unit tests for Standing Orders — tick lifecycle, completion, actions, caps."""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.db.models import WidgetInstance
from app.domain.errors import DomainError, ValidationError
from app.services import standing_orders as so
from app.services.native_app_widgets import (
    dispatch_native_widget_action,
    get_native_widget_spec,
)


def _build_instance(state: dict) -> WidgetInstance:
    return WidgetInstance(
        id=uuid.uuid4(),
        widget_kind="native_app",
        widget_ref=so.STANDING_ORDER_WIDGET_REF,
        scope_kind="dashboard",
        scope_ref=f"standing_order/{uuid.uuid4()}",
        config={},
        state=state,
    )


def _initial_state(**overrides):
    base = so.build_initial_state(
        goal="Unit test standing order",
        strategy="timer",
        strategy_args={},
        interval_seconds=60,
        max_iterations=50,
        completion={"kind": "after_n_iterations", "n": 3},
        message_on_complete="done",
        owning_bot_id="bot-1",
        owning_channel_id=str(uuid.uuid4()),
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_strategy_accepts_poll_url_with_url():
    so.validate_strategy("poll_url", {"url": "https://example.com/status"})


def test_validate_strategy_rejects_unknown():
    with pytest.raises(ValidationError):
        so.validate_strategy("carrier_pigeon", {})


def test_validate_strategy_rejects_poll_url_without_url():
    with pytest.raises(ValidationError):
        so.validate_strategy("poll_url", {})


def test_validate_strategy_rejects_non_http_url():
    with pytest.raises(ValidationError):
        so.validate_strategy("poll_url", {"url": "file:///etc/passwd"})


def test_validate_completion_accepts_all_known_kinds():
    so.validate_completion({"kind": "after_n_iterations", "n": 5})
    so.validate_completion(
        {"kind": "state_field_equals", "path": "strategy_state.x", "value": 1}
    )
    so.validate_completion({"kind": "deadline_passed", "at": "2099-01-01T00:00:00+00:00"})


def test_validate_completion_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        so.validate_completion({"kind": "llm_says_so"})


def test_validate_completion_caps_iteration_count():
    with pytest.raises(ValidationError):
        so.validate_completion({"kind": "after_n_iterations", "n": so.MAX_ITERATIONS_HARD_CAP + 1})


# ---------------------------------------------------------------------------
# Completion evaluation (pure, deterministic — no LLM)
# ---------------------------------------------------------------------------


def test_evaluate_completion_after_n_iterations():
    state = {"iterations": 2}
    assert so.evaluate_completion(state, {"kind": "after_n_iterations", "n": 3}) == (False, None)
    state = {"iterations": 3}
    terminal, reason = so.evaluate_completion(state, {"kind": "after_n_iterations", "n": 3})
    assert terminal is True
    assert "3" in (reason or "")


def test_evaluate_completion_state_field_equals_matches_nested_path():
    state = {"strategy_state": {"last_status_code": 200}}
    terminal, _reason = so.evaluate_completion(
        state,
        {"kind": "state_field_equals", "path": "strategy_state.last_status_code", "value": 200},
    )
    assert terminal is True


def test_evaluate_completion_state_field_equals_does_not_match():
    state = {"strategy_state": {"last_status_code": 404}}
    terminal, reason = so.evaluate_completion(
        state,
        {"kind": "state_field_equals", "path": "strategy_state.last_status_code", "value": 200},
    )
    assert terminal is False
    assert reason is None


def test_evaluate_completion_deadline_passed():
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    assert so.evaluate_completion({}, {"kind": "deadline_passed", "at": past})[0] is True
    assert so.evaluate_completion({}, {"kind": "deadline_passed", "at": future})[0] is False


# ---------------------------------------------------------------------------
# Cron tick lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_tick_advances_and_reschedules_when_not_terminal():
    instance = _build_instance(_initial_state())
    db = AsyncMock()
    before_next = instance.state["next_tick_at"]

    await so.on_tick(db, instance)

    assert instance.state["iterations"] == 1
    assert instance.state["status"] == "running"
    assert instance.state["next_tick_at"] != before_next
    assert instance.state["last_tick_at"] is not None


@pytest.mark.asyncio
async def test_on_tick_terminates_when_completion_fires():
    # completion after 1 iteration; no message emission path (owning_channel_id won't resolve)
    state = _initial_state(
        completion={"kind": "after_n_iterations", "n": 1},
        owning_channel_id="00000000-0000-0000-0000-000000000000",
    )
    instance = _build_instance(state)

    db = AsyncMock()
    db.get.return_value = None  # channel lookup returns None -> terminal emit short-circuits

    await so.on_tick(db, instance)

    assert instance.state["status"] == "done"
    assert instance.state["next_tick_at"] is None
    assert instance.state["terminal_reason"]


@pytest.mark.asyncio
async def test_on_tick_ignores_paused_instance():
    state = _initial_state()
    state["status"] = "paused"
    instance = _build_instance(state)
    db = AsyncMock()

    await so.on_tick(db, instance)

    assert instance.state["iterations"] == 0
    assert instance.state["status"] == "paused"


@pytest.mark.asyncio
async def test_on_tick_marks_unknown_strategy_failed():
    state = _initial_state(strategy="mystery_meat")
    instance = _build_instance(state)
    db = AsyncMock()
    db.get.return_value = None

    await so.on_tick(db, instance)

    assert instance.state["status"] == "failed"


@pytest.mark.asyncio
async def test_on_tick_appends_log_entry_with_ring_buffer_cap():
    # seed a standing order that already has many log entries
    state = _initial_state(
        strategy="poll_url",
        strategy_args={"url": "https://example.com/"},
    )
    state["log"] = [{"at": "2020-01-01T00:00:00+00:00", "text": f"old-{i}"} for i in range(30)]
    instance = _build_instance(state)
    db = AsyncMock()

    # Stub the strategy to return a trivial logged result so we don't hit the network.
    patched = so.TickResult(log_entry="patched GET ok", state_patch={"last_status_code": 200})
    with patch.object(so, "_tick_poll_url", AsyncMock(return_value=patched)):
        so._STRATEGY_HANDLERS["poll_url"] = so._tick_poll_url
        await so.on_tick(db, instance)

    # Log is capped at _LOG_RETAIN entries, newest last
    assert len(instance.state["log"]) == so._LOG_RETAIN
    assert instance.state["log"][-1]["text"] == "patched GET ok"
    assert instance.state["strategy_state"]["last_status_code"] == 200


# ---------------------------------------------------------------------------
# Action dispatcher (pause / resume / cancel / edit_goal)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_standing_order_pause_and_resume_round_trip(db_session):
    instance = await so.create_standing_order_instance(
        db_session, initial_state=_initial_state()
    )

    paused = await dispatch_native_widget_action(
        db_session, instance=instance, action="pause", args={}
    )
    assert paused == {"status": "paused"}
    assert instance.state["status"] == "paused"

    resumed = await dispatch_native_widget_action(
        db_session, instance=instance, action="resume", args={}
    )
    assert resumed["status"] == "running"
    assert instance.state["status"] == "running"
    assert instance.state["next_tick_at"]


@pytest.mark.asyncio
async def test_standing_order_cancel_is_terminal(db_session):
    instance = await so.create_standing_order_instance(
        db_session, initial_state=_initial_state()
    )

    cancelled = await dispatch_native_widget_action(
        db_session, instance=instance, action="cancel", args={}
    )
    assert cancelled == {"status": "cancelled"}
    assert instance.state["status"] == "cancelled"
    assert instance.state["next_tick_at"] is None
    assert instance.state["terminal_reason"]

    # Cancelling again should fail — already terminal.
    with pytest.raises((DomainError, ValidationError)):
        await dispatch_native_widget_action(
            db_session, instance=instance, action="cancel", args={}
        )


@pytest.mark.asyncio
async def test_standing_order_edit_goal_updates_state(db_session):
    instance = await so.create_standing_order_instance(
        db_session, initial_state=_initial_state()
    )

    result = await dispatch_native_widget_action(
        db_session,
        instance=instance,
        action="edit_goal",
        args={"goal": "Refined goal"},
    )
    assert result == {"goal": "Refined goal"}
    assert instance.state["goal"] == "Refined goal"


@pytest.mark.asyncio
async def test_standing_order_edit_goal_rejects_empty(db_session):
    instance = await so.create_standing_order_instance(
        db_session, initial_state=_initial_state()
    )

    with pytest.raises((DomainError, ValidationError)):
        await dispatch_native_widget_action(
            db_session,
            instance=instance,
            action="edit_goal",
            args={"goal": "   "},
        )


@pytest.mark.asyncio
async def test_standing_order_pause_rejects_terminal_instance(db_session):
    state = _initial_state()
    state["status"] = "done"
    state["next_tick_at"] = None
    instance = await so.create_standing_order_instance(
        db_session, initial_state=state
    )

    with pytest.raises((DomainError, ValidationError)):
        await dispatch_native_widget_action(
            db_session, instance=instance, action="pause", args={}
        )


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


def test_standing_order_spec_is_registered_with_cron():
    spec = get_native_widget_spec(so.STANDING_ORDER_WIDGET_REF)
    assert spec is not None
    assert spec.cron is not None
    assert spec.cron.handler is so.on_tick
    action_ids = {action.id for action in spec.actions}
    assert {"pause", "resume", "cancel", "edit_goal"}.issubset(action_ids)


# ---------------------------------------------------------------------------
# Per-bot active cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_count_active_for_bot_only_counts_running():
    rows = []
    for status in ("running", "running", "paused", "done", "cancelled"):
        rows.append(
            _build_instance(_initial_state(status=status, owning_bot_id="bot-x"))
        )
    # Different bot — not counted
    rows.append(_build_instance(_initial_state(owning_bot_id="bot-y")))

    active = so.count_active_for_bot(rows, "bot-x")
    assert active == 2
