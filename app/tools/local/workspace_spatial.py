"""Bot-facing tools for Spatial Canvas movement and awareness."""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.agent.context import (
    current_bot_id,
    current_channel_id,
    current_spatial_move_steps_used,
    current_spatial_tug_steps_used,
)
from app.db.engine import async_session
from app.domain.errors import NotFoundError, ValidationError
from app.tools.registry import register


_DESCRIBE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "describe_canvas_neighborhood",
        "description": (
            "Describe your current Spatial Canvas position and nearby objects. "
            "Use before moving or tugging objects."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

_MOVE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "move_on_canvas",
        "description": (
            "Move your bot node on the Spatial Canvas by grid steps. Positive "
            "dx moves right, negative dx left; positive dy moves down, negative dy up. "
            "Movement is capped by the current channel's spatial policy."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "dx_steps": {"type": "integer"},
                "dy_steps": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["dx_steps", "dy_steps"],
        },
    },
}

_TUG_SCHEMA = {
    "type": "function",
    "function": {
        "name": "tug_spatial_object",
        "description": (
            "Move a very nearby Spatial Canvas object by grid steps. Only use "
            "node ids reported as tuggable by describe_canvas_neighborhood."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target_node_id": {"type": "string"},
                "dx_steps": {"type": "integer"},
                "dy_steps": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["target_node_id", "dx_steps", "dy_steps"],
        },
    },
}

_INSPECT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "inspect_nearby_spatial_object",
        "description": (
            "Read bounded details for a nearby Spatial Canvas object. This does "
            "not grant widget action-handler access."
        ),
        "parameters": {
            "type": "object",
            "properties": {"target_node_id": {"type": "string"}},
            "required": ["target_node_id"],
        },
    },
}


def _scope() -> tuple[str | None, uuid.UUID | None, str | None]:
    bot_id = current_bot_id.get()
    channel_id = current_channel_id.get()
    if not bot_id:
        return None, None, "No bot context available."
    if not channel_id:
        return None, None, "No channel context available."
    return bot_id, channel_id, None


def _step_count(dx_steps: int, dy_steps: int) -> int:
    return abs(int(dx_steps)) + abs(int(dy_steps))


@register(_DESCRIBE_SCHEMA, safety_tier="readonly", requires_bot_context=True, requires_channel_context=True)
async def describe_canvas_neighborhood() -> str:
    bot_id, channel_id, err = _scope()
    if err:
        return json.dumps({"error": err})
    assert bot_id and channel_id
    async with async_session() as db:
        from app.services.workspace_spatial import build_canvas_neighborhood
        payload = await build_canvas_neighborhood(db, channel_id=channel_id, bot_id=bot_id)
    return json.dumps(payload, default=str)


@register(_MOVE_SCHEMA, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True)
async def move_on_canvas(dx_steps: int, dy_steps: int, reason: str | None = None) -> str:
    bot_id, channel_id, err = _scope()
    if err:
        return json.dumps({"error": err})
    assert bot_id and channel_id
    steps = _step_count(dx_steps, dy_steps)
    async with async_session() as db:
        from app.services.workspace_spatial import get_channel_bot_spatial_policy, move_bot_node, serialize_node
        policy = await get_channel_bot_spatial_policy(db, channel_id, bot_id)
        used = current_spatial_move_steps_used.get()
        if used + steps > policy["max_move_steps_per_turn"]:
            return json.dumps({"error": f"Movement budget exceeded: used {used}, requested {steps}, max {policy['max_move_steps_per_turn']}."})
        try:
            node = await move_bot_node(
                db,
                channel_id=channel_id,
                bot_id=bot_id,
                dx_steps=dx_steps,
                dy_steps=dy_steps,
                reason=reason,
            )
        except (NotFoundError, ValidationError) as exc:
            return json.dumps({"error": str(exc)})
    current_spatial_move_steps_used.set(current_spatial_move_steps_used.get() + steps)
    return json.dumps({"node": serialize_node(node), "steps_used": current_spatial_move_steps_used.get()}, default=str)


@register(_TUG_SCHEMA, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True)
async def tug_spatial_object(
    target_node_id: str,
    dx_steps: int,
    dy_steps: int,
    reason: str | None = None,
) -> str:
    bot_id, channel_id, err = _scope()
    if err:
        return json.dumps({"error": err})
    assert bot_id and channel_id
    try:
        node_id = uuid.UUID(target_node_id)
    except (TypeError, ValueError):
        return json.dumps({"error": f"Invalid target_node_id: {target_node_id!r}"})
    steps = _step_count(dx_steps, dy_steps)
    async with async_session() as db:
        from app.services.workspace_spatial import get_channel_bot_spatial_policy, serialize_node, tug_spatial_node
        policy = await get_channel_bot_spatial_policy(db, channel_id, bot_id)
        used = current_spatial_tug_steps_used.get()
        if used + steps > policy["max_tug_steps_per_turn"]:
            return json.dumps({"error": f"Tug budget exceeded: used {used}, requested {steps}, max {policy['max_tug_steps_per_turn']}."})
        try:
            node = await tug_spatial_node(
                db,
                channel_id=channel_id,
                bot_id=bot_id,
                target_node_id=node_id,
                dx_steps=dx_steps,
                dy_steps=dy_steps,
                reason=reason,
            )
        except (NotFoundError, ValidationError) as exc:
            return json.dumps({"error": str(exc)})
    current_spatial_tug_steps_used.set(current_spatial_tug_steps_used.get() + steps)
    return json.dumps({"node": serialize_node(node), "steps_used": current_spatial_tug_steps_used.get()}, default=str)


@register(_INSPECT_SCHEMA, safety_tier="readonly", requires_bot_context=True, requires_channel_context=True)
async def inspect_nearby_spatial_object(target_node_id: str) -> str:
    bot_id, channel_id, err = _scope()
    if err:
        return json.dumps({"error": err})
    assert bot_id and channel_id
    try:
        node_id = uuid.UUID(target_node_id)
    except (TypeError, ValueError):
        return json.dumps({"error": f"Invalid target_node_id: {target_node_id!r}"})
    async with async_session() as db:
        from app.services.workspace_spatial import inspect_nearby_spatial_object as inspect
        try:
            payload = await inspect(db, channel_id=channel_id, bot_id=bot_id, target_node_id=node_id)
        except (NotFoundError, ValidationError) as exc:
            return json.dumps({"error": str(exc)})
    return json.dumps(payload, default=str)
