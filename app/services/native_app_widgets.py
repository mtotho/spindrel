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
