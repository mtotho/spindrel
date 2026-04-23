"""Registry + persistence helpers for first-party native app widgets."""
from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.db.models import WidgetDashboardPin, WidgetInstance
from app.services.widget_contracts import build_native_widget_contract


NATIVE_APP_CONTENT_TYPE = "application/vnd.spindrel.native-app+json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class NativeWidgetActionSpec:
    id: str
    description: str
    args_schema: dict[str, Any] = field(default_factory=dict)
    returns_schema: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "description": self.description,
            "args_schema": self.args_schema or {"type": "object", "properties": {}},
        }
        if self.returns_schema:
            data["returns_schema"] = self.returns_schema
        return data


@dataclass(frozen=True)
class NativeWidgetSpec:
    widget_ref: str
    name: str
    display_label: str
    description: str
    icon: str | None = None
    supported_scopes: tuple[str, ...] = ("channel", "dashboard")
    default_config: dict[str, Any] = field(default_factory=dict)
    config_schema: dict[str, Any] | None = None
    default_state: dict[str, Any] = field(default_factory=dict)
    actions: tuple[NativeWidgetActionSpec, ...] = ()
    panel_title: str | None = None
    show_panel_title: bool | None = None

    def catalog_entry(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "scope": "core",
            "format": "native_app",
            "widget_kind": "native_app",
            "widget_binding": "standalone",
            "theme_support": "none",
            "display_label": self.display_label,
            "description": self.description,
            "icon": self.icon,
            "panel_title": self.panel_title,
            "show_panel_title": self.show_panel_title,
            "widget_ref": self.widget_ref,
            "actions": [action.as_dict() for action in self.actions],
            "supported_scopes": list(self.supported_scopes),
            "config_schema": copy.deepcopy(
                self.config_schema
                if self.config_schema is not None
                else {"type": "object", "properties": {}}
            ),
            "widget_contract": build_native_widget_contract(
                actions=[action.as_dict() for action in self.actions],
                supported_scopes=self.supported_scopes,
                instantiation_kind="native_catalog",
            ),
        }


_NOTES_ACTIONS = (
    NativeWidgetActionSpec(
        id="replace_body",
        description="Replace the full note body with new markdown/plain text content.",
        args_schema={
            "type": "object",
            "properties": {
                "body": {
                    "type": "string",
                    "description": "Full note body to save.",
                },
            },
            "required": ["body"],
        },
        returns_schema={
            "type": "object",
            "properties": {
                "body": {"type": "string"},
                "updated_at": {"type": "string"},
            },
            "required": ["body", "updated_at"],
        },
    ),
    NativeWidgetActionSpec(
        id="append_text",
        description="Append text to the end of the current note body.",
        args_schema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to append to the note body.",
                },
            },
            "required": ["text"],
        },
        returns_schema={
            "type": "object",
            "properties": {
                "body": {"type": "string"},
                "updated_at": {"type": "string"},
            },
            "required": ["body", "updated_at"],
        },
    ),
    NativeWidgetActionSpec(
        id="clear",
        description="Clear the note body.",
        args_schema={"type": "object", "properties": {}},
        returns_schema={
            "type": "object",
            "properties": {"cleared": {"type": "boolean"}},
            "required": ["cleared"],
        },
    ),
)

_TODO_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "done": {"type": "boolean"},
        "position": {"type": "integer"},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
    },
    "required": ["id", "title", "done", "position", "created_at", "updated_at"],
}

_TODO_COUNTS_SCHEMA = {
    "type": "object",
    "properties": {
        "total": {"type": "integer"},
        "open": {"type": "integer"},
        "completed": {"type": "integer"},
    },
    "required": ["total", "open", "completed"],
}

_TODO_ACTIONS = (
    NativeWidgetActionSpec(
        id="add_item",
        description="Add a new open todo item to the list.",
        args_schema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Todo text to add.",
                },
            },
            "required": ["title"],
        },
        returns_schema={
            "type": "object",
            "properties": {
                "item": _TODO_ITEM_SCHEMA,
                "counts": _TODO_COUNTS_SCHEMA,
            },
            "required": ["item", "counts"],
        },
    ),
    NativeWidgetActionSpec(
        id="toggle_item",
        description="Toggle a todo item's done state, or force it with `done`.",
        args_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Todo item id."},
                "done": {
                    "type": "boolean",
                    "description": "Optional explicit done state. Omit to flip the current value.",
                },
            },
            "required": ["id"],
        },
        returns_schema={
            "type": "object",
            "properties": {
                "item": _TODO_ITEM_SCHEMA,
                "counts": _TODO_COUNTS_SCHEMA,
            },
            "required": ["item", "counts"],
        },
    ),
    NativeWidgetActionSpec(
        id="rename_item",
        description="Rename an existing todo item.",
        args_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Todo item id."},
                "title": {"type": "string", "description": "New todo title."},
            },
            "required": ["id", "title"],
        },
        returns_schema={
            "type": "object",
            "properties": {"item": _TODO_ITEM_SCHEMA},
            "required": ["item"],
        },
    ),
    NativeWidgetActionSpec(
        id="delete_item",
        description="Delete a todo item entirely.",
        args_schema={
            "type": "object",
            "properties": {"id": {"type": "string", "description": "Todo item id."}},
            "required": ["id"],
        },
        returns_schema={
            "type": "object",
            "properties": {
                "deleted": {"type": "boolean"},
                "id": {"type": "string"},
                "counts": _TODO_COUNTS_SCHEMA,
            },
            "required": ["deleted", "id", "counts"],
        },
    ),
    NativeWidgetActionSpec(
        id="reorder_items",
        description="Reorder the open todo lane using the complete ordered id list.",
        args_schema={
            "type": "object",
            "properties": {
                "ordered_ids": {
                    "type": "array",
                    "description": "Ordered ids for every open todo item.",
                },
            },
            "required": ["ordered_ids"],
        },
        returns_schema={
            "type": "object",
            "properties": {
                "items": {"type": "array", "items": _TODO_ITEM_SCHEMA},
                "counts": _TODO_COUNTS_SCHEMA,
            },
            "required": ["items", "counts"],
        },
    ),
    NativeWidgetActionSpec(
        id="clear_completed",
        description="Delete every completed todo item.",
        args_schema={"type": "object", "properties": {}},
        returns_schema={
            "type": "object",
            "properties": {
                "cleared": {"type": "integer"},
                "items": {"type": "array", "items": _TODO_ITEM_SCHEMA},
                "counts": _TODO_COUNTS_SCHEMA,
            },
            "required": ["cleared", "items", "counts"],
        },
    ),
)


_REGISTRY: dict[str, NativeWidgetSpec] = {
    "core/notes_native": NativeWidgetSpec(
        widget_ref="core/notes_native",
        name="notes_native",
        display_label="Notes",
        description="First-party native notes widget with persistent state and bot-callable actions.",
        icon="notebook-pen",
        supported_scopes=("channel", "dashboard"),
        default_state={
            "body": "",
            "created_at": "",
            "updated_at": "",
        },
        actions=_NOTES_ACTIONS,
        panel_title="Notes",
        show_panel_title=True,
    ),
    "core/todo_native": NativeWidgetSpec(
        widget_ref="core/todo_native",
        name="todo_native",
        display_label="Todo",
        description="First-party native todo widget with persistent task state and bot-callable actions.",
        icon="check-square",
        supported_scopes=("channel", "dashboard"),
        default_state={
            "items": [],
            "created_at": "",
            "updated_at": "",
        },
        actions=_TODO_ACTIONS,
        panel_title="Todo",
        show_panel_title=True,
    ),
}


def list_native_widget_catalog_entries() -> list[dict[str, Any]]:
    return [spec.catalog_entry() for spec in _REGISTRY.values()]


def get_native_widget_spec(widget_ref: str) -> NativeWidgetSpec | None:
    return _REGISTRY.get(widget_ref)


def get_native_widget_actions(widget_ref: str) -> list[dict[str, Any]]:
    spec = get_native_widget_spec(widget_ref)
    if spec is None:
        return []
    return [action.as_dict() for action in spec.actions]


def _scope_for_dashboard(
    dashboard_key: str,
    source_channel_id: uuid.UUID | None,
) -> tuple[str, str]:
    if dashboard_key.startswith("channel:") and source_channel_id is not None:
        return "channel", str(source_channel_id)
    return "dashboard", dashboard_key


def _merge_defaults(
    defaults: dict[str, Any],
    override: dict[str, Any] | None,
) -> dict[str, Any]:
    data = copy.deepcopy(defaults)
    if override:
        data.update(copy.deepcopy(override))
    return data


def build_native_widget_preview_envelope(
    widget_ref: str,
    *,
    display_label: str | None = None,
    state: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    widget_instance_id: uuid.UUID | str | None = None,
    source_bot_id: str | None = None,
) -> dict[str, Any]:
    spec = get_native_widget_spec(widget_ref)
    if spec is None:
        raise HTTPException(404, f"Unknown native widget: {widget_ref!r}")
    body = {
        "widget_ref": widget_ref,
        "widget_kind": "native_app",
        "display_label": display_label or spec.display_label,
        "state": _merge_defaults(spec.default_state, state),
        "config": _merge_defaults(spec.default_config, config),
        "actions": [action.as_dict() for action in spec.actions],
    }
    if widget_instance_id is not None:
        body["widget_instance_id"] = str(widget_instance_id)
    return {
        "content_type": NATIVE_APP_CONTENT_TYPE,
        "body": body,
        "plain_body": spec.description,
        "display": "inline",
        "display_label": display_label or spec.display_label,
        "source_bot_id": source_bot_id,
        "panel_title": spec.panel_title,
        "show_panel_title": spec.show_panel_title,
    }


async def get_or_create_native_widget_instance(
    db: AsyncSession,
    *,
    widget_ref: str,
    dashboard_key: str,
    source_channel_id: uuid.UUID | None,
    config: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> WidgetInstance:
    spec = get_native_widget_spec(widget_ref)
    if spec is None:
        raise HTTPException(404, f"Unknown native widget: {widget_ref!r}")
    scope_kind, scope_ref = _scope_for_dashboard(dashboard_key, source_channel_id)
    if scope_kind not in spec.supported_scopes:
        raise HTTPException(
            400,
            f"Native widget {widget_ref!r} does not support scope {scope_kind!r}",
        )

    existing = (
        await db.execute(
            select(WidgetInstance).where(
                WidgetInstance.widget_kind == "native_app",
                WidgetInstance.widget_ref == widget_ref,
                WidgetInstance.scope_kind == scope_kind,
                WidgetInstance.scope_ref == scope_ref,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if config:
            existing.config = _merge_defaults(existing.config or {}, config)
            flag_modified(existing, "config")
        if state:
            existing.state = _merge_defaults(existing.state or {}, state)
            flag_modified(existing, "state")
        return existing

    merged_state = _merge_defaults(spec.default_state, state)
    merged_config = _merge_defaults(spec.default_config, config)
    if not merged_state.get("created_at"):
        merged_state["created_at"] = _now_iso()
    if not merged_state.get("updated_at"):
        merged_state["updated_at"] = merged_state["created_at"]
    instance = WidgetInstance(
        widget_kind="native_app",
        widget_ref=widget_ref,
        scope_kind=scope_kind,
        scope_ref=scope_ref,
        config=merged_config,
        state=merged_state,
    )
    db.add(instance)
    await db.flush()
    return instance


def build_envelope_for_native_instance(
    instance: WidgetInstance,
    *,
    display_label: str | None = None,
    source_bot_id: str | None = None,
) -> dict[str, Any]:
    return build_native_widget_preview_envelope(
        instance.widget_ref,
        display_label=display_label,
        state=instance.state or {},
        config=instance.config or {},
        widget_instance_id=instance.id,
        source_bot_id=source_bot_id,
    )


def _validate_args_against_schema(
    schema: dict[str, Any],
    args: dict[str, Any] | None,
) -> None:
    args = args or {}
    required = schema.get("required") or []
    props = schema.get("properties") or {}
    for key in required:
        if key not in args:
            raise HTTPException(400, f"Missing required action arg: {key}")
    for key, value in args.items():
        prop = props.get(key)
        if not isinstance(prop, dict):
            continue
        typ = prop.get("type")
        if typ == "string" and not isinstance(value, str):
            raise HTTPException(400, f"Action arg {key!r} must be a string")
        if typ == "boolean" and not isinstance(value, bool):
            raise HTTPException(400, f"Action arg {key!r} must be a boolean")
        if typ == "integer" and not (isinstance(value, int) and not isinstance(value, bool)):
            raise HTTPException(400, f"Action arg {key!r} must be an integer")
        if typ == "number" and not (
            (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)
        ):
            raise HTTPException(400, f"Action arg {key!r} must be a number")
        if typ == "object" and not isinstance(value, dict):
            raise HTTPException(400, f"Action arg {key!r} must be an object")
        if typ == "array" and not isinstance(value, list):
            raise HTTPException(400, f"Action arg {key!r} must be an array")


def _todo_state(instance: WidgetInstance) -> dict[str, Any]:
    state = copy.deepcopy(instance.state or {})
    state.setdefault("items", [])
    state.setdefault("created_at", "")
    state.setdefault("updated_at", "")
    return state


def _serialize_todo_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "title": str(item.get("title") or ""),
        "done": bool(item.get("done")),
        "position": int(item.get("position") or 0),
        "created_at": str(item.get("created_at") or ""),
        "updated_at": str(item.get("updated_at") or ""),
    }


def _normalize_todo_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    open_items = [_serialize_todo_item(item) for item in items if not item.get("done")]
    completed_items = [_serialize_todo_item(item) for item in items if item.get("done")]
    for idx, item in enumerate(open_items):
        item["position"] = idx
    for idx, item in enumerate(completed_items):
        item["position"] = idx
    return open_items + completed_items


def _todo_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    completed = sum(1 for item in items if item["done"])
    total = len(items)
    return {"total": total, "open": total - completed, "completed": completed}


def _require_todo_title(args: dict[str, Any] | None) -> str:
    title = str((args or {}).get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title is required")
    if len(title) > 500:
        raise HTTPException(400, "title is too long (max 500 chars)")
    return title


def _find_todo_item(items: list[dict[str, Any]], item_id: str) -> tuple[int, dict[str, Any]]:
    for idx, item in enumerate(items):
        if item["id"] == item_id:
            return idx, item
    raise HTTPException(404, f"unknown todo item id: {item_id}")


async def _dispatch_notes_action(
    db: AsyncSession,
    instance: WidgetInstance,
    action: str,
    args: dict[str, Any] | None,
) -> Any:
    state = copy.deepcopy(instance.state or {})
    body = str(state.get("body") or "")
    created_at = str(state.get("created_at") or "") or _now_iso()
    updated_at = _now_iso()
    if action == "replace_body":
        body = str((args or {}).get("body") or "")
        result: Any = {"body": body, "updated_at": updated_at}
    elif action == "append_text":
        body = body + str((args or {}).get("text") or "")
        result = {"body": body, "updated_at": updated_at}
    elif action == "clear":
        body = ""
        result = {"cleared": True}
    else:
        raise HTTPException(404, f"Unsupported native widget action: {action!r}")
    state["body"] = body
    state["created_at"] = created_at
    state["updated_at"] = updated_at
    instance.state = state
    flag_modified(instance, "state")
    await db.flush()
    return result


async def _dispatch_todo_action(
    db: AsyncSession,
    instance: WidgetInstance,
    action: str,
    args: dict[str, Any] | None,
) -> Any:
    state = _todo_state(instance)
    items = _normalize_todo_items(list(state.get("items") or []))
    now = _now_iso()
    created_at = str(state.get("created_at") or "") or now

    if action == "add_item":
        item = {
            "id": str(uuid.uuid4()),
            "title": _require_todo_title(args),
            "done": False,
            "position": sum(1 for existing in items if not existing["done"]),
            "created_at": now,
            "updated_at": now,
        }
        items.append(item)
        items = _normalize_todo_items(items)
        result: Any = {"item": next(entry for entry in items if entry["id"] == item["id"])}
    elif action == "toggle_item":
        item_id = str((args or {}).get("id") or "").strip()
        if not item_id:
            raise HTTPException(400, "id is required")
        idx, current = _find_todo_item(items, item_id)
        next_done = not current["done"] if "done" not in (args or {}) else bool((args or {})["done"])
        current = copy.deepcopy(current)
        current["done"] = next_done
        current["updated_at"] = now
        items[idx] = current
        items = _normalize_todo_items(items)
        result = {"item": next(entry for entry in items if entry["id"] == item_id)}
    elif action == "rename_item":
        item_id = str((args or {}).get("id") or "").strip()
        if not item_id:
            raise HTTPException(400, "id is required")
        title = _require_todo_title(args)
        idx, current = _find_todo_item(items, item_id)
        current = copy.deepcopy(current)
        current["title"] = title
        current["updated_at"] = now
        items[idx] = current
        items = _normalize_todo_items(items)
        result = {"item": next(entry for entry in items if entry["id"] == item_id)}
    elif action == "delete_item":
        item_id = str((args or {}).get("id") or "").strip()
        if not item_id:
            raise HTTPException(400, "id is required")
        idx, _current = _find_todo_item(items, item_id)
        del items[idx]
        items = _normalize_todo_items(items)
        result = {"deleted": True, "id": item_id}
    elif action == "reorder_items":
        ordered_ids = [str(value) for value in ((args or {}).get("ordered_ids") or [])]
        open_items = [item for item in items if not item["done"]]
        completed_items = [item for item in items if item["done"]]
        if ordered_ids != [item["id"] for item in open_items] and set(ordered_ids) != {item["id"] for item in open_items}:
            raise HTTPException(400, "ordered_ids must list each open item exactly once")
        if len(ordered_ids) != len(open_items):
            raise HTTPException(400, "ordered_ids must list each open item exactly once")
        lookup = {item["id"]: item for item in open_items}
        items = [lookup[item_id] for item_id in ordered_ids] + completed_items
        items = _normalize_todo_items(items)
        result = {"items": items}
    elif action == "clear_completed":
        cleared = sum(1 for item in items if item["done"])
        items = [item for item in items if not item["done"]]
        items = _normalize_todo_items(items)
        result = {"cleared": cleared, "items": items}
    else:
        raise HTTPException(404, f"Unsupported native widget action: {action!r}")

    state["items"] = items
    state["created_at"] = created_at
    state["updated_at"] = now
    instance.state = state
    flag_modified(instance, "state")
    await db.flush()
    result.setdefault("counts", _todo_counts(items))
    return result


async def dispatch_native_widget_action(
    db: AsyncSession,
    *,
    instance: WidgetInstance,
    action: str,
    args: dict[str, Any] | None,
) -> Any:
    spec = get_native_widget_spec(instance.widget_ref)
    if spec is None:
        raise HTTPException(404, f"Unknown native widget: {instance.widget_ref!r}")
    action_spec = next((candidate for candidate in spec.actions if candidate.id == action), None)
    if action_spec is None:
        raise HTTPException(
            404,
            f"Unknown action {action!r} for native widget {instance.widget_ref!r}",
        )
    _validate_args_against_schema(action_spec.args_schema, args or {})

    if instance.widget_ref == "core/notes_native":
        return await _dispatch_notes_action(db, instance, action, args)
    if instance.widget_ref == "core/todo_native":
        return await _dispatch_todo_action(db, instance, action, args)

    raise HTTPException(404, f"No native action dispatcher registered for {instance.widget_ref!r}")


async def get_widget_instance(
    db: AsyncSession,
    widget_instance_id: uuid.UUID | str,
) -> WidgetInstance | None:
    instance_id = widget_instance_id
    if isinstance(instance_id, str):
        instance_id = uuid.UUID(instance_id)
    return await db.get(WidgetInstance, instance_id)


async def get_native_widget_instance_for_pin(
    db: AsyncSession,
    pin: WidgetDashboardPin,
) -> WidgetInstance | None:
    if pin.widget_instance_id is None:
        return None
    return await db.get(WidgetInstance, pin.widget_instance_id)


def pin_supports_native_widget(pin: WidgetDashboardPin | dict[str, Any]) -> bool:
    envelope = pin.envelope if hasattr(pin, "envelope") else (pin.get("envelope") or {})
    return envelope.get("content_type") == NATIVE_APP_CONTENT_TYPE


def extract_native_widget_ref_from_envelope(envelope: dict[str, Any]) -> str | None:
    if envelope.get("content_type") != NATIVE_APP_CONTENT_TYPE:
        return None
    body = envelope.get("body")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            return None
    if not isinstance(body, dict):
        return None
    widget_ref = body.get("widget_ref")
    return str(widget_ref) if isinstance(widget_ref, str) and widget_ref else None


def action_manifest_for_pin(
    pin: WidgetDashboardPin | dict[str, Any],
) -> list[dict[str, Any]]:
    envelope = pin.envelope if hasattr(pin, "envelope") else (pin.get("envelope") or {})
    widget_ref = extract_native_widget_ref_from_envelope(envelope)
    if not widget_ref:
        return []
    return get_native_widget_actions(widget_ref)
