from __future__ import annotations

import json

import pytest

from app.services.widget_presets import (
    list_widget_presets,
    list_binding_options,
    preview_widget_preset,
    serialize_widget_preset,
    resolve_runtime_args,
    WidgetPresetValidationError,
)
from app.services.widget_preview import PreviewEnvelope, PreviewOut


def _manifest() -> dict:
    return {
        "homeassistant": {
            "tool_families": {
                "official": {
                    "label": "Official Home Assistant MCP",
                    "tools": ["GetLiveContext", "HassTurnOn", "HassTurnOff", "HassLightSet"],
                },
                "community": {
                    "label": "Community ha-mcp",
                    "tools": ["ha_get_state", "ha_search_entities"],
                },
            },
            "widget_presets": {
                "homeassistant-light-card": {
                    "name": "Light Card",
                    "layout_hints": {
                        "preferred_zone": "grid",
                        "min_cells": {"w": 4, "h": 4},
                    },
                    "tool_name": "GetLiveContext",
                    "tool_family": "official",
                    "tool_dependencies": ["GetLiveContext", "HassTurnOn", "HassTurnOff", "HassLightSet"],
                    "binding_schema": {
                        "type": "object",
                        "properties": {
                            "entity_id": {
                                "type": "string",
                                "ui": {
                                    "control": "picker",
                                    "source": "homeassistant.light_entities",
                                },
                            },
                        },
                    },
                    "binding_sources": {
                        "homeassistant.light_entities": {
                            "tool": "GetLiveContext",
                            "args": {},
                            "transform": "integrations.homeassistant.bindings:live_context_options",
                            "params": {"domains": ["light"]},
                        },
                    },
                    "default_config": {
                        "preset_variant": "light_card",
                        "show_brightness": True,
                        "action_target": "name",
                    },
                    "runtime": {
                        "tool_args": {},
                    },
                },
            },
        },
    }


def test_list_widget_presets_reads_manifest(monkeypatch):
    monkeypatch.setattr("app.services.widget_presets.get_all_manifests", lambda: _manifest())
    presets = list_widget_presets()
    assert [preset["id"] for preset in presets] == ["homeassistant-light-card"]
    assert presets[0]["integration_id"] == "homeassistant"


def test_serialize_widget_preset_exposes_resulting_contract(monkeypatch):
    monkeypatch.setattr("app.services.widget_presets.get_all_manifests", lambda: _manifest())
    monkeypatch.setattr(
        "app.services.widget_presets.build_public_fields_for_tool_widget",
        lambda tool_name, instantiation_kind: {
            "config_schema": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                },
            },
            "widget_contract": {
                "definition_kind": "tool_widget",
                "binding_kind": "tool_bound",
                "instantiation_kind": instantiation_kind,
                "auth_model": "server_context",
                "state_model": "tool_result",
                "refresh_model": "state_poll",
                "theme_model": "component_host",
                "supported_scopes": [],
                "actions": [],
            },
        },
    )
    preset = serialize_widget_preset(list_widget_presets()[0])
    assert preset["config_schema"]["properties"]["entity_id"]["type"] == "string"
    assert preset["widget_contract"]["definition_kind"] == "tool_widget"
    assert preset["widget_contract"]["instantiation_kind"] == "preset"
    assert preset["layout_hints"] == {
        "preferred_zone": "grid",
        "min_cells": {"w": 4, "h": 4},
    }
    assert preset["widget_contract"]["layout_hints"] == preset["layout_hints"]
    assert preset["dependency_contract"] == {
        "tool_family": {
            "id": "official",
            "label": "Official Home Assistant MCP",
            "tools": ["GetLiveContext", "HassTurnOn", "HassTurnOff", "HassLightSet"],
        },
        "tools": ["GetLiveContext", "HassLightSet", "HassTurnOff", "HassTurnOn"],
    }


@pytest.mark.asyncio
async def test_list_binding_options_normalizes_live_context(monkeypatch):
    monkeypatch.setattr("app.services.widget_presets.get_all_manifests", lambda: _manifest())

    async def _exec(_tool_name, _args, bot_id=None, channel_id=None):
        return (
            {
                "result": (
                    "Live Context: overview\n"
                    "- names: Office Desk LED Strip\n"
                    "  domain: light\n"
                    "  state: 'on'\n"
                    "  areas: Office\n"
                    "- names: Kitchen Temperature Temperature\n"
                    "  domain: sensor\n"
                    "  state: '71.69'\n"
                    "  areas: Kitchen\n"
                ),
            },
            None,
        )

    monkeypatch.setattr("app.services.tool_execution.execute_tool_with_context", _exec)
    options = await list_binding_options(
        preset_id="homeassistant-light-card",
        source_id="homeassistant.light_entities",
        source_bot_id="bot-1",
        source_channel_id=None,
    )
    assert options == [{
        "value": "light.office_desk_led_strip",
        "label": "Office Desk LED Strip",
        "description": "light.office_desk_led_strip",
        "group": "Office",
        "meta": {
            "domain": "light",
            "area": "Office",
            "properties": [
                {"value": "name", "label": "Name"},
                {"value": "state", "label": "State"},
                {"value": "last_changed", "label": "Last Changed"},
                {"value": "last_updated", "label": "Last Updated"},
                {"value": "none", "label": "None"},
            ],
        },
    }]


@pytest.mark.asyncio
async def test_list_binding_options_includes_attribute_property_metadata(monkeypatch):
    monkeypatch.setattr("app.services.widget_presets.get_all_manifests", lambda: _manifest())

    async def _exec(_tool_name, _args, bot_id=None, channel_id=None):
        return (
            {
                "result": (
                    "Live Context: overview\n"
                    "- names: Office Desk LED Strip\n"
                    "  domain: light\n"
                    "  state: 'on'\n"
                    "  areas: Office\n"
                    "  attributes:\n"
                    "    brightness: '180'\n"
                    "    color_temp_kelvin: '2700'\n"
                ),
            },
            None,
        )

    monkeypatch.setattr("app.services.tool_execution.execute_tool_with_context", _exec)
    options = await list_binding_options(
        preset_id="homeassistant-light-card",
        source_id="homeassistant.light_entities",
        source_bot_id="bot-1",
        source_channel_id=None,
    )
    assert options[0]["meta"]["properties"] == [
        {"value": "name", "label": "Name"},
        {"value": "state", "label": "State"},
        {"value": "last_changed", "label": "Last Changed"},
        {"value": "last_updated", "label": "Last Updated"},
        {"value": "none", "label": "None"},
        {"value": "attr:brightness", "label": "Brightness"},
        {"value": "attr:color_temp_kelvin", "label": "Color Temp Kelvin"},
    ]


@pytest.mark.asyncio
async def test_list_binding_options_resolves_bare_mcp_tool_names(monkeypatch):
    monkeypatch.setattr("app.services.widget_presets.get_all_manifests", lambda: _manifest())
    monkeypatch.setattr("app.tools.registry.is_local_tool", lambda _name: False)
    monkeypatch.setattr(
        "app.tools.mcp.resolve_mcp_tool_name",
        lambda name: "homeassistant-GetLiveContext" if name == "GetLiveContext" else None,
    )
    monkeypatch.setattr(
        "app.tools.mcp.is_mcp_tool",
        lambda name: name == "homeassistant-GetLiveContext",
    )

    async def _call_mcp_tool(tool_name: str, arguments: str) -> str:
        assert tool_name == "homeassistant-GetLiveContext"
        assert json.loads(arguments) == {}
        return json.dumps({
            "result": (
                "Live Context: overview\n"
                "- names: Office Desk LED Strip\n"
                "  domain: light\n"
                "  state: 'on'\n"
                "  areas: Office\n"
            ),
        })

    monkeypatch.setattr("app.tools.mcp.call_mcp_tool", _call_mcp_tool)
    monkeypatch.setattr("app.agent.bots._registry", {"bot-1": object()})

    options = await list_binding_options(
        preset_id="homeassistant-light-card",
        source_id="homeassistant.light_entities",
        source_bot_id="bot-1",
        source_channel_id=None,
    )
    assert options == [{
        "value": "light.office_desk_led_strip",
        "label": "Office Desk LED Strip",
        "description": "light.office_desk_led_strip",
        "group": "Office",
        "meta": {
            "domain": "light",
            "area": "Office",
            "properties": [
                {"value": "name", "label": "Name"},
                {"value": "state", "label": "State"},
                {"value": "last_changed", "label": "Last Changed"},
                {"value": "last_updated", "label": "Last Updated"},
                {"value": "none", "label": "None"},
            ],
        },
    }]


def test_resolve_runtime_args_substitutes_config(monkeypatch):
    monkeypatch.setattr("app.services.widget_presets.get_all_manifests", lambda: _manifest())
    preset = list_widget_presets()[0]
    args = resolve_runtime_args(
        preset=preset,
        config={"entity_id": "light.office_desk_led_strip"},
        source_bot_id="bot-1",
        source_channel_id=None,
    )
    assert args == {}


@pytest.mark.asyncio
async def test_preview_widget_preset_executes_underlying_tool(monkeypatch):
    monkeypatch.setattr("app.services.widget_presets.get_all_manifests", lambda: _manifest())

    async def _exec(tool_name, args, bot_id=None, channel_id=None):
        assert tool_name == "GetLiveContext"
        assert args == {}
        assert bot_id == "bot-1"
        return ({
            "result": (
                "Live Context: overview\n"
                "- names: Office Desk LED Strip\n"
                "  domain: light\n"
                "  state: 'on'\n"
                "  areas: Office\n"
            ),
        }, None)

    async def _preview(_db, *, tool_name, sample_payload, widget_config, source_bot_id, source_channel_id):
        assert tool_name == "GetLiveContext"
        assert "Office Desk LED Strip" in sample_payload["result"]
        assert widget_config["preset_variant"] == "light_card"
        assert widget_config["entity_id"] == "light.office_desk_led_strip"
        assert source_bot_id == "bot-1"
        return PreviewOut(
            ok=True,
            envelope=PreviewEnvelope(
                content_type="application/vnd.spindrel.components+json",
                body="{}",
                display="inline",
                display_label="Office Desk LED Strip",
            ),
        )

    monkeypatch.setattr("app.services.tool_execution.execute_tool_with_context", _exec)
    monkeypatch.setattr("app.services.widget_presets.preview_active_widget_for_tool", _preview)

    preview, resolved_config, tool_args = await preview_widget_preset(
        None,
        preset_id="homeassistant-light-card",
        config={"entity_id": "light.office_desk_led_strip"},
        source_bot_id="bot-1",
        source_channel_id=None,
    )
    assert preview.ok is True
    assert resolved_config == {
        "preset_variant": "light_card",
        "show_brightness": True,
        "action_target": "name",
        "entity_id": "light.office_desk_led_strip",
    }
    assert tool_args == {}
    assert preview.widget_contract is None or preview.widget_contract["definition_kind"] == "tool_widget"


def test_list_widget_presets_rejects_mixed_tool_family(monkeypatch):
    manifest = _manifest()
    preset = manifest["homeassistant"]["widget_presets"]["homeassistant-light-card"]
    preset["tool_name"] = "ha_get_state"
    preset["tool_dependencies"] = ["GetLiveContext", "ha_get_state"]
    monkeypatch.setattr("app.services.widget_presets.get_all_manifests", lambda: manifest)

    with pytest.raises(WidgetPresetValidationError, match="outside tool_family 'official'"):
        list_widget_presets()


def test_list_widget_presets_rejects_invalid_binding_schema(monkeypatch):
    manifest = _manifest()
    preset = manifest["homeassistant"]["widget_presets"]["homeassistant-light-card"]
    preset["binding_schema"] = {"type": "array"}
    monkeypatch.setattr("app.services.widget_presets.get_all_manifests", lambda: manifest)

    with pytest.raises(WidgetPresetValidationError, match="binding_schema"):
        list_widget_presets()
