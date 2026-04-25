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

_PIN_WIDGET_SCHEMA = {
    "type": "function",
    "function": {
        "name": "pin_spatial_widget",
        "description": (
            "Pin a widget directly onto the Spatial Canvas as a bot-owned "
            "workspace widget. Requires this channel's spatial widget "
            "management policy."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "widget": {"type": "string"},
                "source_kind": {
                    "type": "string",
                    "enum": ["builtin", "integration", "channel", "library"],
                },
                "source_integration_id": {"type": "string"},
                "display_label": {"type": "string"},
                "world_x": {"type": "number"},
                "world_y": {"type": "number"},
                "world_w": {"type": "number"},
                "world_h": {"type": "number"},
                "tool_args": {"type": "object"},
                "widget_config": {"type": "object"},
            },
            "required": ["widget"],
        },
    },
}

_MOVE_WIDGET_SCHEMA = {
    "type": "function",
    "function": {
        "name": "move_spatial_widget",
        "description": (
            "Move one of your bot-owned Spatial Canvas widgets by grid steps. "
            "Use node ids from describe_canvas_neighborhood."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target_node_id": {"type": "string"},
                "dx_steps": {"type": "integer"},
                "dy_steps": {"type": "integer"},
            },
            "required": ["target_node_id", "dx_steps", "dy_steps"],
        },
    },
}

_RESIZE_WIDGET_SCHEMA = {
    "type": "function",
    "function": {
        "name": "resize_spatial_widget",
        "description": "Resize one of your bot-owned Spatial Canvas widgets.",
        "parameters": {
            "type": "object",
            "properties": {
                "target_node_id": {"type": "string"},
                "world_w": {"type": "number"},
                "world_h": {"type": "number"},
            },
            "required": ["target_node_id", "world_w", "world_h"],
        },
    },
}

_REMOVE_WIDGET_SCHEMA = {
    "type": "function",
    "function": {
        "name": "remove_spatial_widget",
        "description": "Remove one of your bot-owned Spatial Canvas widgets.",
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


async def _owned_spatial_widget(db, node_id: uuid.UUID, bot_id: str):
    from app.db.models import WidgetDashboardPin
    from app.services.workspace_spatial import get_node

    node = await get_node(db, node_id)
    if not node.widget_pin_id:
        raise ValidationError("Target is not a spatial widget.")
    pin = await db.get(WidgetDashboardPin, node.widget_pin_id)
    if pin is None:
        raise NotFoundError("Spatial widget pin not found.")
    if pin.source_bot_id != bot_id:
        raise ValidationError("You can only manage spatial widgets you created.")
    return node, pin


async def _ensure_widget_management(db, channel_id: uuid.UUID, bot_id: str) -> dict[str, Any]:
    from app.services.workspace_spatial import get_channel_bot_spatial_policy

    policy = await get_channel_bot_spatial_policy(db, channel_id, bot_id)
    if not policy["enabled"] or not policy["allow_spatial_widget_management"]:
        raise ValidationError("Spatial widget management is not enabled for this bot in this channel.")
    return policy


@register(_PIN_WIDGET_SCHEMA, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True)
async def pin_spatial_widget(
    widget: str,
    source_kind: str = "library",
    source_integration_id: str | None = None,
    display_label: str | None = None,
    world_x: float | None = None,
    world_y: float | None = None,
    world_w: float | None = None,
    world_h: float | None = None,
    tool_args: dict[str, Any] | None = None,
    widget_config: dict[str, Any] | None = None,
) -> str:
    bot_id, channel_id, err = _scope()
    if err:
        return json.dumps({"error": err})
    assert bot_id and channel_id
    async with async_session() as db:
        try:
            await _ensure_widget_management(db, channel_id, bot_id)
        except ValidationError as exc:
            return json.dumps({"error": str(exc)})

    from app.tools.local.dashboard_tools import (
        _envelope_for_entry,
        _instantiate_tool_renderer_entry,
        _resolve_widget_entry,
    )

    entry, resolve_err = await _resolve_widget_entry(
        widget,
        source_kind=source_kind,
        source_integration_id=source_integration_id,
        channel_id=channel_id,
        bot_id=bot_id,
    )
    template_tool_name: str | None = None
    widget_origin: dict[str, Any]
    if resolve_err and source_kind == "library":
        template_tool_name, template_envelope, template_err = await _instantiate_tool_renderer_entry(
            widget,
            tool_args=tool_args,
            widget_config=widget_config,
            bot_id=bot_id,
            channel_id=channel_id,
            auth_scope="bot",
        )
        if template_err:
            return json.dumps({"error": template_err})
        assert template_envelope is not None
        envelope = template_envelope
        widget_origin = {
            "definition_kind": "tool_widget",
            "instantiation_kind": "spatial_library_pin",
            "tool_name": template_tool_name,
        }
    else:
        if resolve_err:
            return json.dumps({"error": resolve_err})
        assert entry is not None
        envelope = _envelope_for_entry(
            entry,
            channel_id=channel_id,
            source_bot_id=bot_id,
            display_label=display_label,
        )
        native_widget_ref = entry.get("widget_ref")
        if envelope.get("content_type") == "application/vnd.spindrel.native-app+json" and native_widget_ref:
            widget_origin = {
                "definition_kind": "native_widget",
                "instantiation_kind": "spatial_native_catalog",
                "widget_ref": str(native_widget_ref),
            }
        else:
            widget_origin = {
                "definition_kind": "html_widget",
                "instantiation_kind": "spatial_library_pin",
                "source_bot_id": bot_id,
            }
            for key_name in ("source_library_ref", "source_path", "source_kind", "source_channel_id", "source_integration_id"):
                value = envelope.get(key_name)
                if isinstance(value, str) and value.strip():
                    widget_origin[key_name] = value.strip()

    async with async_session() as db:
        from app.services.workspace_spatial import pin_widget_to_canvas, serialize_node

        try:
            pin, node = await pin_widget_to_canvas(
                db,
                source_kind="adhoc",
                tool_name=template_tool_name or (entry or {}).get("widget_ref") or "emit_html_widget",
                envelope=envelope,
                source_channel_id=channel_id,
                source_bot_id=bot_id,
                tool_args=tool_args if template_tool_name else None,
                widget_config=widget_config if template_tool_name else None,
                widget_origin=widget_origin,
                display_label=display_label or envelope.get("display_label"),
                world_x=world_x,
                world_y=world_y,
                world_w=world_w or 360.0,
                world_h=world_h or 240.0,
            )
        except Exception as exc:  # noqa: BLE001 - surface tool failure to the model
            return json.dumps({"error": str(exc)})
    return json.dumps({"pin_id": str(pin.id), "node": serialize_node(node, pin), "llm": f"Pinned spatial widget {pin.display_label or pin.tool_name}."}, default=str)


@register(_MOVE_WIDGET_SCHEMA, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True)
async def move_spatial_widget(target_node_id: str, dx_steps: int, dy_steps: int) -> str:
    bot_id, channel_id, err = _scope()
    if err:
        return json.dumps({"error": err})
    assert bot_id and channel_id
    try:
        node_id = uuid.UUID(target_node_id)
    except (TypeError, ValueError):
        return json.dumps({"error": f"Invalid target_node_id: {target_node_id!r}"})
    async with async_session() as db:
        from app.services.workspace_spatial import serialize_node, update_node_position

        try:
            policy = await _ensure_widget_management(db, channel_id, bot_id)
            node, pin = await _owned_spatial_widget(db, node_id, bot_id)
            step = float(policy["step_world_units"])
            node = await update_node_position(
                db,
                node.id,
                world_x=node.world_x + int(dx_steps) * step,
                world_y=node.world_y + int(dy_steps) * step,
            )
        except (NotFoundError, ValidationError) as exc:
            return json.dumps({"error": str(exc)})
    return json.dumps({"node": serialize_node(node, pin)}, default=str)


@register(_RESIZE_WIDGET_SCHEMA, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True)
async def resize_spatial_widget(target_node_id: str, world_w: float, world_h: float) -> str:
    bot_id, channel_id, err = _scope()
    if err:
        return json.dumps({"error": err})
    assert bot_id and channel_id
    try:
        node_id = uuid.UUID(target_node_id)
    except (TypeError, ValueError):
        return json.dumps({"error": f"Invalid target_node_id: {target_node_id!r}"})
    async with async_session() as db:
        from app.services.workspace_spatial import serialize_node, update_node_position

        try:
            await _ensure_widget_management(db, channel_id, bot_id)
            node, pin = await _owned_spatial_widget(db, node_id, bot_id)
            node = await update_node_position(db, node.id, world_w=world_w, world_h=world_h)
        except (NotFoundError, ValidationError) as exc:
            return json.dumps({"error": str(exc)})
    return json.dumps({"node": serialize_node(node, pin)}, default=str)


@register(_REMOVE_WIDGET_SCHEMA, safety_tier="mutating", requires_bot_context=True, requires_channel_context=True)
async def remove_spatial_widget(target_node_id: str) -> str:
    bot_id, channel_id, err = _scope()
    if err:
        return json.dumps({"error": err})
    assert bot_id and channel_id
    try:
        node_id = uuid.UUID(target_node_id)
    except (TypeError, ValueError):
        return json.dumps({"error": f"Invalid target_node_id: {target_node_id!r}"})
    async with async_session() as db:
        from app.services.workspace_spatial import delete_node

        try:
            await _ensure_widget_management(db, channel_id, bot_id)
            node, pin = await _owned_spatial_widget(db, node_id, bot_id)
            await delete_node(db, node.id)
        except (NotFoundError, ValidationError) as exc:
            return json.dumps({"error": str(exc)})
    return json.dumps({"removed_node_id": str(node_id), "removed_pin_id": str(pin.id)})
