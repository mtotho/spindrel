from __future__ import annotations

import json

import pytest

from app.services.widget_presets import (
    list_widget_presets,
    list_binding_options,
    preview_widget_preset,
    resolve_runtime_args,
)
from app.services.widget_preview import PreviewEnvelope, PreviewOut


def _manifest() -> dict:
    return {
        "homeassistant": {
            "widget_presets": {
                "homeassistant-light-card": {
                    "name": "Light Card",
                    "tool_name": "ha_get_state",
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
                    },
                    "runtime": {
                        "tool_args": {"entity_id": "{{config.entity_id}}"},
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
        "meta": {"domain": "light", "area": "Office"},
    }]


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
        "meta": {"domain": "light", "area": "Office"},
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
    assert args == {"entity_id": "light.office_desk_led_strip"}


@pytest.mark.asyncio
async def test_preview_widget_preset_executes_underlying_tool(monkeypatch):
    monkeypatch.setattr("app.services.widget_presets.get_all_manifests", lambda: _manifest())

    async def _exec(tool_name, args, bot_id=None, channel_id=None):
        assert tool_name == "ha_get_state"
        assert args == {"entity_id": "light.office_desk_led_strip"}
        assert bot_id == "bot-1"
        return ({
            "data": {
                "entity_id": "light.office_desk_led_strip",
                "state": "on",
                "attributes": {"friendly_name": "Office Desk LED Strip"},
            },
        }, None)

    async def _preview(_db, *, tool_name, sample_payload, widget_config, source_bot_id, source_channel_id):
        assert tool_name == "ha_get_state"
        assert sample_payload["data"]["entity_id"] == "light.office_desk_led_strip"
        assert widget_config["preset_variant"] == "light_card"
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
        "entity_id": "light.office_desk_led_strip",
    }
    assert tool_args == {"entity_id": "light.office_desk_led_strip"}
