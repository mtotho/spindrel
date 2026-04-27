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


def build_public_fields_for_pin(
    *,
    tool_name: str,
    envelope: dict[str, Any],
    source_bot_id: str | None,
    widget_origin: dict[str, Any] | None = None,
    widget_contract_snapshot: dict[str, Any] | None = None,
    config_schema_snapshot: dict[str, Any] | None = None,
    widget_presentation_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = build_pin_contract_metadata(
        tool_name=tool_name,
        envelope=envelope,
        source_bot_id=source_bot_id,
        widget_origin=widget_origin,
        widget_contract_snapshot=widget_contract_snapshot,
        config_schema_snapshot=config_schema_snapshot,
        widget_presentation_snapshot=widget_presentation_snapshot,
    )
    return {
        "config_schema": metadata["config_schema"],
        "widget_contract": metadata["widget_contract"],
        "widget_presentation": metadata["widget_presentation"],
    }


def build_pin_contract_metadata(
    *,
    tool_name: str,
    envelope: dict[str, Any],
    source_bot_id: str | None,
    widget_origin: dict[str, Any] | None = None,
    provenance_confidence: str | None = None,
    widget_contract_snapshot: dict[str, Any] | None = None,
    config_schema_snapshot: dict[str, Any] | None = None,
    widget_presentation_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    origin = (
        copy.deepcopy(widget_origin)
        if isinstance(widget_origin, dict) and widget_origin
        else infer_pin_origin(
            tool_name=tool_name,
            envelope=envelope,
            source_bot_id=source_bot_id,
        )
    )
    confidence = (
        provenance_confidence
        if isinstance(provenance_confidence, str) and provenance_confidence.strip()
        else ("authoritative" if widget_origin else "inferred")
    )
    live_fields = build_public_fields_from_origin(
        origin,
        tool_name=tool_name,
        envelope=envelope,
        source_bot_id=source_bot_id,
    )
    config_schema = (
        live_fields.get("config_schema")
        if live_fields.get("config_schema") is not None
        else normalize_config_schema(config_schema_snapshot)
    )
    widget_presentation = (
        live_fields.get("widget_presentation")
        if live_fields.get("widget_presentation") is not None
        else _merge_presentation_with_defaults(
            copy.deepcopy(widget_presentation_snapshot)
            if isinstance(widget_presentation_snapshot, dict)
            else None,
            fallback_layout_hints=(
                widget_contract_snapshot.get("layout_hints")
                if isinstance(widget_contract_snapshot, dict)
                else None
            ),
        )
    )
    widget_contract = (
        live_fields.get("widget_contract")
        if live_fields.get("widget_contract") is not None
        else copy.deepcopy(widget_contract_snapshot)
        if isinstance(widget_contract_snapshot, dict)
        else None
    )
    return {
        "widget_origin": origin,
        "provenance_confidence": confidence,
        "config_schema": config_schema,
        "widget_presentation": widget_presentation,
        "widget_contract": widget_contract,
        "config_schema_snapshot": copy.deepcopy(config_schema) if config_schema is not None else None,
        "widget_presentation_snapshot": copy.deepcopy(widget_presentation) if widget_presentation is not None else None,
        "widget_contract_snapshot": copy.deepcopy(widget_contract) if widget_contract is not None else None,
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


def infer_pin_origin(
    *,
    tool_name: str,
    envelope: dict[str, Any],
    source_bot_id: str | None,
) -> WidgetOrigin:
    content_type = envelope.get("content_type")
    if content_type == "application/vnd.spindrel.native-app+json":
        body = envelope.get("body")
        widget_ref = None
        if isinstance(body, dict):
            raw_ref = body.get("widget_ref")
            if isinstance(raw_ref, str) and raw_ref.strip():
                widget_ref = raw_ref.strip()
        if widget_ref:
            return {
                "definition_kind": "native_widget",
                "instantiation_kind": "native_catalog",
                "widget_ref": widget_ref,
            }

    instantiation_kind = _pin_instantiation_kind(envelope, tool_name)
    source_preset_id = envelope.get("source_preset_id")
    if isinstance(source_preset_id, str) and source_preset_id.strip():
        origin: WidgetOrigin = {
            "definition_kind": "tool_widget",
            "instantiation_kind": "preset",
            "tool_name": tool_name,
            "preset_id": source_preset_id.strip(),
        }
        template_id = envelope.get("template_id")
        if isinstance(template_id, str) and template_id.strip():
            origin["template_id"] = template_id.strip()
        try:
            from app.services.widget_presets import get_widget_preset

            preset = get_widget_preset(source_preset_id.strip())
            tool_family = preset.get("tool_family")
            if isinstance(tool_family, str) and tool_family.strip():
                origin["tool_family"] = tool_family.strip()
        except Exception:
            pass
        return origin

    tool_fields = build_public_fields_for_tool_widget(
        tool_name,
        instantiation_kind=instantiation_kind,
    )
    if tool_fields["widget_contract"] is not None:
        origin = {
            "definition_kind": "tool_widget",
            "instantiation_kind": instantiation_kind,
            "tool_name": tool_name,
        }
        template_id = envelope.get("template_id")
        if isinstance(template_id, str) and template_id.strip():
            origin["template_id"] = template_id.strip()
        return origin

    origin = {
        "definition_kind": "html_widget",
        "instantiation_kind": instantiation_kind,
    }
    source_library_ref = envelope.get("source_library_ref")
    if isinstance(source_library_ref, str) and source_library_ref.strip():
        origin["source_library_ref"] = source_library_ref.strip()
    source_path = envelope.get("source_path")
    if isinstance(source_path, str) and source_path.strip():
        origin["source_path"] = source_path.strip()
    source_kind = envelope.get("source_kind")
    if isinstance(source_kind, str) and source_kind.strip():
        origin["source_kind"] = source_kind.strip()
    source_channel_id = envelope.get("source_channel_id")
    if isinstance(source_channel_id, str) and source_channel_id.strip():
        origin["source_channel_id"] = source_channel_id.strip()
    source_integration_id = envelope.get("source_integration_id")
    if isinstance(source_integration_id, str) and source_integration_id.strip():
        origin["source_integration_id"] = source_integration_id.strip()
    resolved_bot_id = (
        origin.get("source_bot_id")
        if isinstance(origin.get("source_bot_id"), str)
        else source_bot_id
    )
    if isinstance(resolved_bot_id, str) and resolved_bot_id.strip():
        origin["source_bot_id"] = resolved_bot_id.strip()
    return origin


def build_public_fields_from_origin(
    origin: WidgetOrigin,
    *,
    tool_name: str,
    envelope: dict[str, Any],
    source_bot_id: str | None,
) -> dict[str, Any]:
    definition_kind = origin.get("definition_kind")
    instantiation_kind = str(origin.get("instantiation_kind") or _pin_instantiation_kind(envelope, tool_name))
    if definition_kind == "native_widget":
        widget_ref = origin.get("widget_ref")
        if isinstance(widget_ref, str) and widget_ref.strip():
            return build_public_fields_for_native_widget(
                widget_ref.strip(),
                instantiation_kind=instantiation_kind,
            )
        return {"config_schema": None, "widget_contract": None, "widget_presentation": None}

    if definition_kind == "tool_widget":
        origin_tool_name = str(origin.get("tool_name") or tool_name)
        if instantiation_kind == "preset":
            preset_id = origin.get("preset_id")
            if isinstance(preset_id, str) and preset_id.strip():
                try:
                    from app.services.widget_presets import get_widget_preset

                    preset = get_widget_preset(preset_id.strip())
                    fields = build_public_fields_for_tool_widget(
                        str(preset.get("tool_name") or origin_tool_name),
                        instantiation_kind="preset",
                    )
                    fields["config_schema"] = normalize_config_schema(
                        preset.get("binding_schema")
                    )
                    preset_presentation = build_widget_presentation(
                        presentation_family=preset.get("presentation_family"),
                        panel_title=preset.get("panel_title"),
                        show_panel_title=preset.get("show_panel_title"),
                        layout_hints=preset.get("layout_hints"),
                    )
                    if fields.get("widget_presentation") is None:
                        fields["widget_presentation"] = preset_presentation
                    else:
                        presentation = copy.deepcopy(fields["widget_presentation"])
                        presentation.update(
                            {
                                key: value
                                for key, value in preset_presentation.items()
                                if value is not None
                            }
                        )
                        fields["widget_presentation"] = _merge_presentation_with_defaults(
                            presentation,
                            fallback_layout_hints=preset.get("layout_hints"),
                        )
                    return fields
                except Exception:
                    pass
        return build_public_fields_for_tool_widget(
            origin_tool_name,
            instantiation_kind=instantiation_kind,
        )

    html_source_bot_id = origin.get("source_bot_id")
    merged_source_bot_id = (
        html_source_bot_id.strip()
        if isinstance(html_source_bot_id, str) and html_source_bot_id.strip()
        else source_bot_id
    )
    html_meta = resolve_html_widget_manifest_for_pin(
        _merge_origin_into_envelope(envelope, origin),
        source_bot_id=merged_source_bot_id,
    ) or {}
    return {
        "config_schema": html_meta.get("config_schema"),
        "widget_presentation": _merge_presentation_with_defaults(
            html_meta.get("widget_presentation"),
        ),
        "widget_contract": build_html_widget_contract(
            auth_model="source_bot" if merged_source_bot_id else "viewer",
            actions=html_meta.get("actions"),
            supported_scopes=html_meta.get("supported_scopes"),
            theme_support=html_meta.get("theme_support") or "html",
            context_export=html_meta.get("context_export"),
            instantiation_kind=instantiation_kind,
        ),
    }


def _merge_origin_into_envelope(
    envelope: dict[str, Any],
    origin: WidgetOrigin,
) -> dict[str, Any]:
    merged = copy.deepcopy(envelope)
    for key in (
        "source_library_ref",
        "source_path",
        "source_kind",
        "source_channel_id",
        "source_integration_id",
        "source_bot_id",
    ):
        value = origin.get(key)
        if isinstance(value, str) and value.strip():
            merged[key] = value.strip()
    return merged


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
