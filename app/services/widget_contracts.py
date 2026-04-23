from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

from app.services.widget_manifest import ManifestError, parse_manifest


WidgetContract = dict[str, Any]
JsonSchema = dict[str, Any]


def normalize_config_schema(schema: object) -> JsonSchema | None:
    if not isinstance(schema, dict):
        return None
    normalized = copy.deepcopy(schema)
    schema_type = normalized.get("type")
    if schema_type is None:
        normalized["type"] = "object"
    elif schema_type != "object":
        return None

    props = normalized.get("properties")
    if props is None:
        normalized["properties"] = {}
    elif not isinstance(props, dict):
        return None

    required = normalized.get("required")
    if required is None:
        normalized["required"] = []
    elif (
        not isinstance(required, list)
        or any(not isinstance(item, str) or not item.strip() for item in required)
    ):
        return None
    return normalized


def _copy_actions(actions: object) -> list[dict[str, Any]]:
    if not isinstance(actions, list):
        return []
    out: list[dict[str, Any]] = []
    for item in actions:
        if isinstance(item, dict):
            out.append(copy.deepcopy(item))
    return out


def _copy_supported_scopes(scopes: object) -> list[str]:
    if not isinstance(scopes, (list, tuple)):
        return []
    return [str(scope) for scope in scopes if isinstance(scope, str) and scope.strip()]


def _html_theme_model(theme_support: str | None) -> str:
    if theme_support == "none":
        return "none"
    return "html_host"


def build_tool_widget_contract(
    *,
    widget_def: dict[str, Any] | None = None,
    actions: object = None,
    supported_scopes: object = None,
    instantiation_kind: str = "direct_tool_call",
) -> WidgetContract:
    widget_def = widget_def or {}
    is_html_mode = isinstance(widget_def.get("html_template"), dict) or widget_def.get("html_template_body") is not None
    return {
        "definition_kind": "tool_widget",
        "binding_kind": "tool_bound",
        "instantiation_kind": instantiation_kind,
        "auth_model": "server_context",
        "state_model": "tool_result",
        "refresh_model": "state_poll" if widget_def.get("state_poll") else "none",
        "theme_model": "html_host" if is_html_mode else "component_host",
        "supported_scopes": _copy_supported_scopes(supported_scopes),
        "actions": _copy_actions(actions or widget_def.get("actions")),
    }


def build_html_widget_contract(
    *,
    auth_model: str = "viewer",
    actions: object = None,
    supported_scopes: object = None,
    theme_support: str | None = "html",
    instantiation_kind: str = "library_pin",
) -> WidgetContract:
    return {
        "definition_kind": "html_widget",
        "binding_kind": "standalone",
        "instantiation_kind": instantiation_kind,
        "auth_model": auth_model,
        "state_model": "bundle_runtime",
        "refresh_model": "widget_runtime",
        "theme_model": _html_theme_model(theme_support),
        "supported_scopes": _copy_supported_scopes(supported_scopes),
        "actions": _copy_actions(actions),
    }


def build_native_widget_contract(
    *,
    actions: object = None,
    supported_scopes: object = None,
    instantiation_kind: str = "native_catalog",
) -> WidgetContract:
    action_list = _copy_actions(actions)
    return {
        "definition_kind": "native_widget",
        "binding_kind": "standalone",
        "instantiation_kind": instantiation_kind,
        "auth_model": "host_native",
        "state_model": "instance_state",
        "refresh_model": "instance_actions" if action_list else "none",
        "theme_model": "native_host",
        "supported_scopes": _copy_supported_scopes(supported_scopes),
        "actions": action_list,
    }


def build_public_contract_fields_for_catalog_entry(
    entry: dict[str, Any],
    *,
    preferred_auth_model: str | None = None,
) -> dict[str, Any]:
    widget_kind = entry.get("widget_kind")
    config_schema = normalize_config_schema(entry.get("config_schema"))
    if widget_kind == "native_app":
        return {
            "config_schema": config_schema,
            "widget_contract": build_native_widget_contract(
                actions=entry.get("actions"),
                supported_scopes=entry.get("supported_scopes"),
                instantiation_kind="native_catalog",
            ),
        }
    if widget_kind == "template":
        return {
            "config_schema": config_schema,
            "widget_contract": build_tool_widget_contract(
                widget_def=entry,
                actions=entry.get("actions"),
                supported_scopes=entry.get("supported_scopes"),
                instantiation_kind="direct_tool_call",
            ),
        }
    return {
        "config_schema": config_schema,
        "widget_contract": build_html_widget_contract(
            auth_model=preferred_auth_model or "viewer",
            actions=entry.get("actions"),
            supported_scopes=entry.get("supported_scopes"),
            theme_support=entry.get("theme_support"),
            instantiation_kind="library_pin",
        ),
    }


def build_public_fields_for_tool_widget(
    tool_name: str,
    *,
    instantiation_kind: str,
) -> dict[str, Any]:
    from app.services.widget_templates import get_widget_template

    entry = get_widget_template(tool_name)
    if entry is None and "-" in tool_name:
        entry = get_widget_template(tool_name.split("-", 1)[1])
    if entry is None:
        return {"config_schema": None, "widget_contract": None}
    config_schema = normalize_config_schema(entry.get("config_schema"))
    return {
        "config_schema": config_schema,
        "widget_contract": build_tool_widget_contract(
            widget_def=entry,
            supported_scopes=entry.get("supported_scopes"),
            actions=entry.get("actions"),
            instantiation_kind=instantiation_kind,
        ),
    }


def build_public_fields_for_native_widget(
    widget_ref: str,
    *,
    instantiation_kind: str,
) -> dict[str, Any]:
    from app.services.native_app_widgets import get_native_widget_spec

    spec = get_native_widget_spec(widget_ref)
    if spec is None:
        return {"config_schema": None, "widget_contract": None}
    config_schema = normalize_config_schema(spec.config_schema)
    return {
        "config_schema": config_schema,
        "widget_contract": build_native_widget_contract(
            actions=[action.as_dict() for action in spec.actions],
            supported_scopes=spec.supported_scopes,
            instantiation_kind=instantiation_kind,
        ),
    }


def resolve_html_widget_manifest_for_pin(
    envelope: dict[str, Any],
    *,
    source_bot_id: str | None = None,
) -> dict[str, Any] | None:
    manifest_path = _resolve_html_widget_manifest_path(envelope, source_bot_id=source_bot_id)
    if manifest_path is None:
        return None
    try:
        manifest = parse_manifest(manifest_path)
    except (ManifestError, OSError):
        return None
    return {
        "config_schema": normalize_config_schema(manifest.config_schema),
        "actions": [spec.as_dict() for spec in manifest.handlers if spec.bot_callable],
        "supported_scopes": [],
        "theme_support": "html",
    }


def build_public_fields_for_pin(
    *,
    tool_name: str,
    envelope: dict[str, Any],
    source_bot_id: str | None,
) -> dict[str, Any]:
    content_type = envelope.get("content_type")
    if content_type == "application/vnd.spindrel.native-app+json":
        body = envelope.get("body")
        widget_ref = None
        if isinstance(body, dict):
            raw_ref = body.get("widget_ref")
            if isinstance(raw_ref, str) and raw_ref.strip():
                widget_ref = raw_ref.strip()
        if widget_ref:
            return build_public_fields_for_native_widget(
                widget_ref,
                instantiation_kind="native_catalog",
            )
        return {"config_schema": None, "widget_contract": None}

    tool_fields = build_public_fields_for_tool_widget(
        tool_name,
        instantiation_kind=_pin_instantiation_kind(envelope, tool_name),
    )
    if tool_fields["widget_contract"] is not None:
        return tool_fields

    html_meta = resolve_html_widget_manifest_for_pin(
        envelope,
        source_bot_id=source_bot_id,
    ) or {}
    return {
        "config_schema": html_meta.get("config_schema"),
        "widget_contract": build_html_widget_contract(
            auth_model="source_bot" if source_bot_id else "viewer",
            actions=html_meta.get("actions"),
            supported_scopes=html_meta.get("supported_scopes"),
            theme_support=html_meta.get("theme_support") or "html",
            instantiation_kind=_pin_instantiation_kind(envelope, tool_name),
        ),
    }


def _pin_instantiation_kind(envelope: dict[str, Any], tool_name: str) -> str:
    source_instantiation_kind = envelope.get("source_instantiation_kind")
    if isinstance(source_instantiation_kind, str) and source_instantiation_kind.strip():
        return source_instantiation_kind.strip()
    if envelope.get("source_library_ref") or envelope.get("source_path"):
        return "library_pin"
    if tool_name == "html_widget":
        return "runtime_emit"
    return "direct_tool_call"


def _resolve_html_widget_manifest_path(
    envelope: dict[str, Any],
    *,
    source_bot_id: str | None,
) -> Path | None:
    source_library_ref = envelope.get("source_library_ref")
    if isinstance(source_library_ref, str) and "/" in source_library_ref:
        scope, name = source_library_ref.split("/", 1)
        widget_dir = _resolve_library_widget_dir(
            scope,
            name,
            source_bot_id=source_bot_id,
        )
        if widget_dir is not None:
            manifest_path = widget_dir / "widget.yaml"
            if manifest_path.is_file():
                return manifest_path

    source_kind = envelope.get("source_kind")
    source_path = envelope.get("source_path")
    if not isinstance(source_path, str) or not source_path.strip():
        return None
    rel_path = source_path.strip()
    if source_kind == "integration":
        integration_id = envelope.get("source_integration_id")
        if isinstance(integration_id, str) and integration_id.strip():
            root = Path(__file__).resolve().parents[2] / "integrations" / integration_id / "widgets"
            manifest_path = (root / rel_path).resolve().parent / "widget.yaml"
            if manifest_path.is_file():
                return manifest_path
    elif source_kind == "channel":
        channel_id = envelope.get("source_channel_id")
        if isinstance(channel_id, str) and channel_id.strip():
            from app.agent.bots import get_bot
            from app.services.channel_workspace import get_channel_workspace_root

            bot = get_bot(source_bot_id) if source_bot_id else None
            if bot is not None:
                try:
                    root = Path(get_channel_workspace_root(channel_id, bot))
                except Exception:
                    return None
                manifest_path = (root / rel_path).resolve().parent / "widget.yaml"
                if _is_path_within(manifest_path, root) and manifest_path.is_file():
                    return manifest_path
    return None


def _resolve_library_widget_dir(
    scope: str,
    name: str,
    *,
    source_bot_id: str | None,
) -> Path | None:
    from app.agent.bots import get_bot
    from app.services.shared_workspace import shared_workspace_service
    from app.services.workspace import workspace_service

    repo_root = Path(__file__).resolve().parents[2]
    if scope == "core":
        widget_dir = repo_root / "app" / "tools" / "local" / "widgets" / name
        return widget_dir if widget_dir.is_dir() else None
    if not source_bot_id:
        return None
    bot = get_bot(source_bot_id)
    if bot is None:
        return None
    if scope == "bot":
        ws_root = workspace_service.get_workspace_root(source_bot_id, bot)
        widget_dir = Path(ws_root) / ".widget_library" / name
        return widget_dir if widget_dir.is_dir() else None
    if scope == "workspace" and bot.shared_workspace_id:
        shared_root = shared_workspace_service.get_host_root(bot.shared_workspace_id)
        widget_dir = Path(shared_root) / ".widget_library" / name
        return widget_dir if widget_dir.is_dir() else None
    return None


def _is_path_within(path: Path, root: Path) -> bool:
    try:
        real_path = path.resolve()
        real_root = root.resolve()
    except OSError:
        return False
    return real_path == real_root or os.fspath(real_path).startswith(os.fspath(real_root) + os.sep)
