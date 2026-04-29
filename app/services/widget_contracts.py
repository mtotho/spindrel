from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

from app.services.widget_manifest import ManifestError, parse_manifest


WidgetContract = dict[str, Any]
JsonSchema = dict[str, Any]
WidgetOrigin = dict[str, Any]
WidgetPresentation = dict[str, Any]

_VALID_CONTEXT_EXPORT_SUMMARY_KINDS = frozenset({"plain_body", "native_state", "server_provider"})
_VALID_CONTEXT_EXPORT_HINT_KINDS = frozenset({"none", "invoke_widget_action", "handler_tools", "custom"})


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


from app.services.widget_layout import normalize_layout_hints  # noqa: E402, F401

# ``normalize_layout_hints`` lives in ``widget_layout`` as the single
# source of truth for layout-hint vocabulary (Cluster 4B.3). Re-exported
# here so callers inside this module can use the same name, and so
# external callers who historically imported it from
# ``app.services.widget_contracts`` don't break.


def normalize_presentation_family(value: object) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"card", "chip", "panel"}:
            return normalized
    return "card"


def normalize_context_export(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    enabled = value.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        return None
    summary_kind = value.get("summary_kind")
    if summary_kind is None:
        summary_kind = "plain_body"
    elif not isinstance(summary_kind, str):
        return None
    else:
        summary_kind = summary_kind.strip()
    if summary_kind not in _VALID_CONTEXT_EXPORT_SUMMARY_KINDS:
        return None
    hint_kind = value.get("hint_kind")
    if hint_kind is None:
        hint_kind = "none"
    elif not isinstance(hint_kind, str):
        return None
    else:
        hint_kind = hint_kind.strip()
    if hint_kind not in _VALID_CONTEXT_EXPORT_HINT_KINDS:
        return None
    out: dict[str, Any] = {
        "enabled": True if enabled is None else enabled,
        "summary_kind": summary_kind,
        "hint_kind": hint_kind,
    }
    hint_text = value.get("hint_text")
    if isinstance(hint_text, str):
        cleaned = hint_text.strip()
        if cleaned:
            out["hint_text"] = cleaned
    return out


def build_widget_presentation(
    *,
    presentation_family: object = None,
    panel_title: object = None,
    show_panel_title: object = None,
    layout_hints: object = None,
) -> WidgetPresentation:
    presentation: WidgetPresentation = {
        "presentation_family": normalize_presentation_family(presentation_family),
        "layout_hints": normalize_layout_hints(layout_hints),
    }
    if isinstance(panel_title, str):
        cleaned = panel_title.strip()
        if cleaned:
            presentation["panel_title"] = cleaned
    if isinstance(show_panel_title, bool):
        presentation["show_panel_title"] = show_panel_title
    return presentation


def _merge_presentation_with_defaults(
    presentation: WidgetPresentation | None,
    *,
    fallback_layout_hints: object = None,
) -> WidgetPresentation | None:
    if not isinstance(presentation, dict):
        base = build_widget_presentation(layout_hints=fallback_layout_hints)
    else:
        base = copy.deepcopy(presentation)
        base.setdefault("presentation_family", "card")
        if base.get("layout_hints") is None:
            base["layout_hints"] = normalize_layout_hints(fallback_layout_hints)
    return base


def _html_theme_model(theme_support: str | None) -> str:
    if theme_support == "none":
        return "none"
    return "html_host"


def build_tool_widget_contract(
    *,
    widget_def: dict[str, Any] | None = None,
    actions: object = None,
    supported_scopes: object = None,
    context_export: object = None,
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
        "layout_hints": normalize_layout_hints(widget_def.get("layout_hints")),
        "context_export": normalize_context_export(context_export or widget_def.get("context_export")),
    }


def build_html_widget_contract(
    *,
    auth_model: str = "viewer",
    actions: object = None,
    supported_scopes: object = None,
    theme_support: str | None = "html",
    context_export: object = None,
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
        "context_export": normalize_context_export(context_export),
    }


def build_native_widget_contract(
    *,
    actions: object = None,
    supported_scopes: object = None,
    layout_hints: object = None,
    context_export: object = None,
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
        "layout_hints": normalize_layout_hints(layout_hints),
        "context_export": normalize_context_export(context_export),
    }


def build_public_contract_fields_for_catalog_entry(
    entry: dict[str, Any],
    *,
    preferred_auth_model: str | None = None,
) -> dict[str, Any]:
    widget_kind = entry.get("widget_kind")
    config_schema = normalize_config_schema(entry.get("config_schema"))
    widget_presentation = build_widget_presentation(
        presentation_family=entry.get("presentation_family"),
        panel_title=entry.get("panel_title"),
        show_panel_title=entry.get("show_panel_title"),
        layout_hints=entry.get("layout_hints"),
    )
    if widget_kind == "native_app":
        return {
            "config_schema": config_schema,
            "widget_presentation": widget_presentation,
            "widget_contract": build_native_widget_contract(
                actions=entry.get("actions"),
                supported_scopes=entry.get("supported_scopes"),
                layout_hints=entry.get("layout_hints"),
                context_export=entry.get("context_export"),
                instantiation_kind="native_catalog",
            ),
        }
    if widget_kind == "template":
        return {
            "config_schema": config_schema,
            "widget_presentation": widget_presentation,
            "widget_contract": build_tool_widget_contract(
                widget_def=entry,
                actions=entry.get("actions"),
                supported_scopes=entry.get("supported_scopes"),
                context_export=entry.get("context_export"),
                instantiation_kind="direct_tool_call",
            ),
        }
    return {
        "config_schema": config_schema,
        "widget_presentation": widget_presentation,
        "widget_contract": build_html_widget_contract(
            auth_model=preferred_auth_model or "viewer",
            actions=entry.get("actions"),
            supported_scopes=entry.get("supported_scopes"),
            theme_support=entry.get("theme_support"),
            context_export=entry.get("context_export"),
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
        return {"config_schema": None, "widget_contract": None, "widget_presentation": None}
    config_schema = normalize_config_schema(entry.get("config_schema"))
    return {
        "config_schema": config_schema,
        "widget_presentation": build_widget_presentation(
            presentation_family=entry.get("presentation_family"),
            panel_title=entry.get("panel_title"),
            show_panel_title=entry.get("show_panel_title"),
            layout_hints=entry.get("layout_hints"),
        ),
        "widget_contract": build_tool_widget_contract(
            widget_def=entry,
            supported_scopes=entry.get("supported_scopes"),
            actions=entry.get("actions"),
            context_export=entry.get("context_export"),
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
        return {"config_schema": None, "widget_contract": None, "widget_presentation": None}
    config_schema = normalize_config_schema(spec.config_schema)
    return {
        "config_schema": config_schema,
        "widget_presentation": build_widget_presentation(
            presentation_family=spec.presentation_family,
            panel_title=spec.panel_title,
            show_panel_title=spec.show_panel_title,
            layout_hints=spec.layout_hints,
        ),
        "widget_contract": build_native_widget_contract(
            actions=[action.as_dict() for action in spec.actions],
            supported_scopes=spec.supported_scopes,
            layout_hints=spec.layout_hints,
            context_export=spec.context_export,
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
        "context_export": normalize_context_export(manifest.context_export),
        "widget_presentation": build_widget_presentation(
            presentation_family=manifest.presentation_family,
            panel_title=manifest.panel_title,
            show_panel_title=manifest.show_panel_title,
            layout_hints=manifest.layout_hints.__dict__ if manifest.layout_hints else None,
        ),
    }


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
            from integrations.discovery import resolve_integration_path

            root = resolve_integration_path(integration_id, "widgets")
            if root is None:
                return None
            manifest_path = (root / rel_path).resolve().parent / "widget.yaml"
            if _is_path_within(manifest_path, root) and manifest_path.is_file():
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
    from app.domain.errors import NotFoundError
    from app.services.shared_workspace import shared_workspace_service
    from app.services.workspace import workspace_service

    repo_root = Path(__file__).resolve().parents[2]
    if scope == "core":
        widget_dir = repo_root / "app" / "tools" / "local" / "widgets" / name
        return widget_dir if widget_dir.is_dir() else None
    if not source_bot_id:
        return None
    try:
        bot = get_bot(source_bot_id)
    except NotFoundError:
        # Pin references a bot that no longer exists (deleted between pin
        # creation and dashboard read). Treat as "no live source" — the
        # snapshot remains the canonical view and confidence is inferred.
        return None
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
