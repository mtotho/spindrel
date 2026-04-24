"""Bot tool for spawning Standing Orders — durable dashboard work items.

A Standing Order is a bot-spawned ``core/standing_order_native`` widget that
ticks on a schedule without an LLM turn per tick, then pings the channel
when it completes or hits a condition. See
``docs/guides/widget-system.md`` → "Standing Orders" for the full design.

This module registers exactly one bot tool: ``spawn_standing_order``. It is
intended to be skill-gated via a ``standing-orders`` skill so the default
bot tool surface stays lean; any bot that loads that skill can use it.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.agent.context import current_bot_id, current_channel_id
from app.services import standing_orders as _so
from app.services.dashboard_pins import create_pin
from app.services.dashboards import DEFAULT_DASHBOARD_KEY
from app.services.native_app_widgets import build_native_widget_preview_envelope
from app.tools.registry import register

logger = logging.getLogger(__name__)


_SPAWN_STANDING_ORDER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "spawn_standing_order",
        "description": (
            "Plant a live, cancellable tile on the channel's dashboard that "
            "ticks on a schedule and pings back in chat when a condition is "
            "met. Use this when the user asks you to 'watch', 'wait for', "
            "'remind me when', 'poll until', or 'tell me if X happens'.\n\n"
            "Each tick runs one step of a simple strategy (zero LLM calls "
            "per tick by default). The tile stays visible the whole time "
            "so the user can pause, edit the goal, or cancel. When the "
            "declared completion condition fires, you post the "
            "`message_on_complete` text as a normal chat message.\n\n"
            "Strategies:\n"
            "  • poll_url — HTTP GET an endpoint each tick; stores "
            "status code and body head in state.\n"
            "  • timer — does nothing per tick; pair with "
            "completion.kind='deadline_passed' for a reminder.\n\n"
            "Completion kinds (explicit, no LLM judging):\n"
            "  • after_n_iterations — {'n': int}\n"
            "  • state_field_equals — "
            "{'path': 'strategy_state.last_status_code', 'value': 200}\n"
            "  • deadline_passed — {'at': ISO8601 timestamp}\n\n"
            "Caps: max 5 active per bot; interval must be >= 10s; max 1000 "
            "iterations. A Standing Order is NOT a sub-session — if the "
            "work needs reasoning per tick, use a sub-session instead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": (
                        "Human-readable goal shown on the tile (e.g. "
                        "'Watch the staging deploy'). <= 500 chars."
                    ),
                },
                "strategy": {
                    "type": "string",
                    "enum": ["poll_url", "timer"],
                    "description": "Which tick strategy to run.",
                },
                "strategy_args": {
                    "type": "object",
                    "description": (
                        "Strategy-specific config. For poll_url: "
                        "{url: str, expect_status?: int, body_contains?: str}. "
                        "For timer: {} (empty)."
                    ),
                },
                "interval_seconds": {
                    "type": "integer",
                    "description": (
                        "Seconds between ticks. Must be >= 10. "
                        "Typical: 30 for a live deploy, 300 for a slow "
                        "integration poll."
                    ),
                },
                "completion": {
                    "type": "object",
                    "description": (
                        "Completion criteria. Required. "
                        "Shape: {kind: 'after_n_iterations'|"
                        "'state_field_equals'|'deadline_passed', ...}. "
                        "See tool description for per-kind args."
                    ),
                },
                "message_on_complete": {
                    "type": "string",
                    "description": (
                        "Optional. Message posted in chat when the order "
                        "finishes. Defaults to a generic 'completed: {goal}' "
                        "if omitted."
                    ),
                },
                "max_iterations": {
                    "type": "integer",
                    "description": (
                        "Optional hard cap on total ticks. Defaults to 1000. "
                        "Lower this if you want a shorter leash."
                    ),
                },
            },
            "required": ["goal", "strategy", "strategy_args", "interval_seconds", "completion"],
        },
    },
}


_RETURNS_SCHEMA = {
    "type": "object",
    "properties": {
        "widget_instance_id": {"type": "string"},
        "dashboard_pin_id": {"type": "string"},
        "next_tick_at": {"type": "string"},
        "status": {"type": "string"},
    },
    "required": ["widget_instance_id", "dashboard_pin_id", "next_tick_at", "status"],
}


@register(
    _SPAWN_STANDING_ORDER_SCHEMA,
    safety_tier="mutating",
    requires_bot_context=True,
    requires_channel_context=True,
    returns=_RETURNS_SCHEMA,
)
async def spawn_standing_order(
    goal: str,
    strategy: str,
    strategy_args: dict[str, Any],
    interval_seconds: int,
    completion: dict[str, Any],
    message_on_complete: str | None = None,
    max_iterations: int | None = None,
) -> str:
    from app.db.engine import async_session

    bot_id = current_bot_id.get()
    if not bot_id:
        return json.dumps({"error": "No bot context available."}, ensure_ascii=False)

    channel_id = current_channel_id.get()
    if not channel_id:
        return json.dumps(
            {"error": "spawn_standing_order requires an active channel context."},
            ensure_ascii=False,
        )

    goal = (goal or "").strip()
    if not goal:
        return json.dumps({"error": "goal is required"}, ensure_ascii=False)
    if len(goal) > 500:
        return json.dumps(
            {"error": "goal must be 500 characters or fewer"},
            ensure_ascii=False,
        )

    if not isinstance(strategy_args, dict):
        strategy_args = {}
    if not isinstance(completion, dict):
        return json.dumps(
            {"error": "completion must be an object"}, ensure_ascii=False
        )

    if not isinstance(interval_seconds, int) or interval_seconds < _so.MIN_INTERVAL_SECONDS:
        return json.dumps(
            {"error": f"interval_seconds must be integer >= {_so.MIN_INTERVAL_SECONDS}"},
            ensure_ascii=False,
        )

    resolved_max_iterations = max_iterations if isinstance(max_iterations, int) and max_iterations > 0 else _so.MAX_ITERATIONS_HARD_CAP
    if resolved_max_iterations > _so.MAX_ITERATIONS_HARD_CAP:
        return json.dumps(
            {"error": f"max_iterations must be <= {_so.MAX_ITERATIONS_HARD_CAP}"},
            ensure_ascii=False,
        )

    try:
        _so.validate_strategy(strategy, strategy_args)
        _so.validate_completion(completion)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc)}, ensure_ascii=False)

    channel_id_str = str(channel_id)
    try:
        channel_uuid = uuid.UUID(channel_id_str)
    except ValueError:
        return json.dumps(
            {"error": f"Invalid channel_id {channel_id_str!r}"},
            ensure_ascii=False,
        )

    async with async_session() as db:
        active_count = await _so.count_active_standing_orders_for_bot(db, bot_id)
        if active_count >= _so.MAX_STANDING_ORDERS_PER_BOT:
            return json.dumps(
                {
                    "error": (
                        f"This bot already has {active_count} active standing "
                        f"orders (cap {_so.MAX_STANDING_ORDERS_PER_BOT}). "
                        "Cancel one before spawning another."
                    )
                },
                ensure_ascii=False,
            )

        initial_state = _so.build_initial_state(
            goal=goal,
            strategy=strategy,
            strategy_args=strategy_args,
            interval_seconds=interval_seconds,
            max_iterations=resolved_max_iterations,
            completion=completion,
            message_on_complete=message_on_complete,
            owning_bot_id=bot_id,
            owning_channel_id=channel_id_str,
        )

        instance = await _so.create_standing_order_instance(
            db, initial_state=initial_state
        )

        envelope = build_native_widget_preview_envelope(
            _so.STANDING_ORDER_WIDGET_REF,
            display_label=goal[:60] or None,
            state=initial_state,
            widget_instance_id=instance.id,
            source_bot_id=bot_id,
        )

        try:
            pin = await create_pin(
                db,
                source_kind="channel",
                tool_name="spawn_standing_order",
                envelope=envelope,
                source_channel_id=channel_uuid,
                source_bot_id=bot_id,
                tool_args={
                    "goal": goal,
                    "strategy": strategy,
                    "interval_seconds": interval_seconds,
                },
                display_label=goal[:60] or None,
                dashboard_key=f"channel:{channel_uuid}",
                zone="grid",
                override_widget_instance=instance,
            )
        except Exception as exc:
            logger.exception("spawn_standing_order: pin creation failed")
            return json.dumps(
                {"error": f"Failed to pin standing order: {exc}"},
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "widget_instance_id": str(instance.id),
                "dashboard_pin_id": str(pin.id),
                "next_tick_at": str(initial_state.get("next_tick_at") or ""),
                "status": "running",
            },
            ensure_ascii=False,
        )
