from __future__ import annotations

import copy
import importlib
import json
from typing import Any

from fastapi import HTTPException

from app.services.integration_manifests import get_all_manifests
from app.services.widget_preview import PreviewEnvelope, preview_active_widget_for_tool
from app.services.widget_templates import _substitute


def _iter_presets() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for integration_id, manifest in get_all_manifests().items():
        presets = manifest.get("widget_presets")
        if not isinstance(presets, dict):
            continue
        for preset_id, raw in presets.items():
            if not isinstance(raw, dict):
                continue
            out.append({
                "id": raw.get("id") or preset_id,
                "integration_id": integration_id,
                **raw,
            })
    return out


def list_widget_presets() -> list[dict[str, Any]]:
    presets = _iter_presets()
    presets.sort(key=lambda item: (item.get("integration_id") or "", item.get("name") or item["id"]))
    return presets


def get_widget_preset(preset_id: str) -> dict[str, Any]:
    for preset in _iter_presets():
        if preset.get("id") == preset_id:
            return preset
    raise HTTPException(404, f"Unknown widget preset '{preset_id}'")


def serialize_widget_preset(preset: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": preset["id"],
        "integration_id": preset.get("integration_id"),
        "name": preset.get("name") or preset["id"],
        "description": preset.get("description"),
        "icon": preset.get("icon"),
        "tool_name": preset.get("tool_name"),
        "binding_schema": copy.deepcopy(preset.get("binding_schema") or {}),
        "binding_sources": copy.deepcopy(preset.get("binding_sources") or {}),
        "default_config": copy.deepcopy(preset.get("default_config") or {}),
    }


def _load_transform(ref: str):
    module_name, func_name = ref.split(":", 1)
    module = importlib.import_module(module_name)
    try:
        return getattr(module, func_name)
    except AttributeError as exc:
        raise HTTPException(500, f"Widget preset transform '{ref}' not found") from exc


def _normalize_tool_result(parsed_result: Any, raw_result: str | None) -> str:
    if isinstance(raw_result, str):
        return raw_result
    if isinstance(parsed_result, str):
        return parsed_result
    try:
        return json.dumps(parsed_result)
    except TypeError:
        return json.dumps({"result": str(parsed_result)})


def _runtime_context(
    *,
    preset: dict[str, Any],
    config: dict[str, Any],
    source_bot_id: str | None,
    source_channel_id: str | None,
    binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "preset": preset,
        "preset_id": preset.get("id"),
        "integration_id": preset.get("integration_id"),
        "config": config,
        "binding": binding or {},
        "scope": {
            "bot_id": source_bot_id,
            "channel_id": source_channel_id,
        },
    }


def resolve_preset_config(preset: dict[str, Any], config: dict[str, Any] | None) -> dict[str, Any]:
    return {
        **(preset.get("default_config") or {}),
        **(config or {}),
    }


async def list_binding_options(
    *,
    preset_id: str,
    source_id: str,
    source_bot_id: str | None,
    source_channel_id: str | None,
) -> list[dict[str, Any]]:
    from app.services.tool_execution import execute_tool_with_context

    preset = get_widget_preset(preset_id)
    source = (preset.get("binding_sources") or {}).get(source_id)
    if not isinstance(source, dict):
        raise HTTPException(404, f"Unknown binding source '{source_id}' for preset '{preset_id}'")
    tool_name = source.get("tool")
    transform_ref = source.get("transform")
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise HTTPException(400, f"Preset '{preset_id}' binding source '{source_id}' missing tool")
    if not isinstance(transform_ref, str) or not transform_ref.strip():
        raise HTTPException(400, f"Preset '{preset_id}' binding source '{source_id}' missing transform")

    parsed_result, raw_result = await execute_tool_with_context(
        tool_name,
        source.get("args") or {},
        bot_id=source_bot_id,
        channel_id=source_channel_id,
    )
    transform = _load_transform(transform_ref)
    options = transform(
        _normalize_tool_result(parsed_result, raw_result),
        {
            "preset_id": preset_id,
            "source_id": source_id,
            "params": source.get("params") or {},
            "source_bot_id": source_bot_id,
            "source_channel_id": source_channel_id,
        },
    )
    if not isinstance(options, list):
        raise HTTPException(500, f"Preset '{preset_id}' binding source '{source_id}' returned invalid options")
    return options


def resolve_runtime_args(
    *,
    preset: dict[str, Any],
    config: dict[str, Any],
    source_bot_id: str | None,
    source_channel_id: str | None,
) -> dict[str, Any]:
    runtime_args = preset.get("runtime", {}).get("tool_args") or {}
    if not isinstance(runtime_args, dict):
        raise HTTPException(400, f"Preset '{preset['id']}' runtime.tool_args must be a mapping")
    return _substitute(
        copy.deepcopy(runtime_args),
        _runtime_context(
            preset=preset,
            config=config,
            source_bot_id=source_bot_id,
            source_channel_id=source_channel_id,
        ),
    )


async def preview_widget_preset(
    db,
    *,
    preset_id: str,
    config: dict[str, Any] | None,
    source_bot_id: str | None,
    source_channel_id: str | None,
):
    from app.services.tool_execution import execute_tool_with_context

    preset = get_widget_preset(preset_id)
    tool_name = preset.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise HTTPException(400, f"Preset '{preset_id}' missing tool_name")

    resolved_config = resolve_preset_config(preset, config)
    tool_args = resolve_runtime_args(
        preset=preset,
        config=resolved_config,
        source_bot_id=source_bot_id,
        source_channel_id=source_channel_id,
    )

    parsed_result, _raw = await execute_tool_with_context(
        tool_name,
        tool_args or {},
        bot_id=source_bot_id,
        channel_id=source_channel_id,
    )
    payload = parsed_result if isinstance(parsed_result, dict) else {"result": parsed_result}
    preview = await preview_active_widget_for_tool(
        db,
        tool_name=tool_name,
        sample_payload=payload,
        widget_config=resolved_config,
        source_bot_id=source_bot_id,
        source_channel_id=source_channel_id,
    )
    return preview, resolved_config, tool_args


def preview_envelope_to_dict(envelope: PreviewEnvelope | None) -> dict[str, Any] | None:
    if envelope is None:
        return None
    return envelope.model_dump(mode="json")
