"""Unit tests for Home Assistant widget transforms.

Fixtures are real payloads captured from the ha-mcp and official HA MCP
servers — see the haos-bot request trace in the PR description.
"""
from __future__ import annotations

import json

import pytest

from integrations.homeassistant.widget_transforms import (
    live_context_summary,
    single_entity_state,
)


# ── ha_get_state / single_entity_state ──

HA_GET_STATE_TEMPERATURE = json.dumps({
    "data": {
        "entity_id": "sensor.kitchen_temperature_temperature",
        "state": "75.344",
        "attributes": {
            "state_class": "measurement",
            "unit_of_measurement": "°F",
            "device_class": "temperature",
            "friendly_name": "Kitchen Temperature Temperature",
        },
        "last_changed": "2026-04-18T03:15:51.821593+00:00",
    },
})

HA_GET_STATE_LIGHT_ON = json.dumps({
    "data": {
        "entity_id": "light.office_desk_led_strip",
        "state": "on",
        "attributes": {
            "friendly_name": "Office Desk LED Strip",
            "brightness": 180,
        },
    },
})


def test_single_entity_state_temperature():
    out = single_entity_state(HA_GET_STATE_TEMPERATURE, {})
    assert out["entity_id"] == "sensor.kitchen_temperature_temperature"
    assert out["friendly_name"] == "Kitchen Temperature Temperature"
    assert out["unit"] == "°F"
    assert out["device_class"] == "temperature"
    assert out["domain"] == "sensor"
    assert out["state"] == "75.344"
    assert out["display_value"] == "75.344°F"
    assert out["is_off"] is True
    assert out["is_on"] is False


def test_single_entity_state_light_on():
    out = single_entity_state(HA_GET_STATE_LIGHT_ON, {})
    assert out["is_on"] is True
    assert out["is_off"] is False
    assert out["domain"] == "light"
    # No unit → state echoed bare
    assert out["display_value"] == "on"


def test_single_entity_state_invalid_json():
    assert single_entity_state("not-json", {}) == {}


def test_single_entity_state_missing_data():
    assert single_entity_state(json.dumps({}), {}) == {}


# ── GetLiveContext / live_context_summary ──

GET_LIVE_CONTEXT_RESULT = {
    "success": True,
    "result": (
        "Live Context: overview\n"
        "- names: Office Desk LED Strip\n"
        "  domain: light\n"
        "  state: 'on'\n"
        "  attributes:\n"
        "    brightness: '180'\n"
        "- names: Bedroom Lamp\n"
        "  domain: light\n"
        "  state: 'off'\n"
        "- names: Kitchen Temperature Temperature\n"
        "  domain: sensor\n"
        "  state: '71.69'\n"
        "  attributes:\n"
        "    unit_of_measurement: °F\n"
        "- names: Living Room TV\n"
        "  domain: media_player\n"
        "  state: playing\n"
        "- names: Front Door\n"
        "  domain: binary_sensor\n"
        "  state: 'off'\n"
    ),
}


def test_live_context_summary_shape():
    out = live_context_summary(GET_LIVE_CONTEXT_RESULT, [])
    # Phantom "Live Context: overview" header is filtered out; five real
    # entities remain (two lights, sensor, media_player, binary_sensor).
    assert out[0]["type"] == "status"
    assert "5 entities" in out[0]["text"]
    # Active = 1 light on + media_player playing = 2
    assert "2 active" in out[0]["text"]


def test_live_context_summary_domain_counts():
    out = live_context_summary(GET_LIVE_CONTEXT_RESULT, [])
    tiles = out[1]
    assert tiles["type"] == "tiles"
    domain_map = {t["label"]: t["value"] for t in tiles["items"]}
    assert domain_map["light"] == "2"
    assert domain_map["sensor"] == "1"
    assert domain_map["media_player"] == "1"
    assert domain_map["binary_sensor"] == "1"


def test_live_context_summary_active_section():
    out = live_context_summary(GET_LIVE_CONTEXT_RESULT, [])
    # Section appears only when there are active entities
    section = next((c for c in out if c.get("type") == "section"), None)
    assert section is not None
    assert "Active now (2)" == section["label"]
    tile_items = section["children"][0]["items"]
    labels = {t["label"] for t in tile_items}
    assert "Office Desk LED Strip" in labels
    assert "Living Room TV" in labels


def test_live_context_summary_no_active_entities():
    payload = {
        "success": True,
        "result": (
            "Live Context\n"
            "- names: Bedroom Lamp\n"
            "  domain: light\n"
            "  state: 'off'\n"
        ),
    }
    out = live_context_summary(payload, [])
    # No section component when nothing is active
    types = [c["type"] for c in out]
    assert "section" not in types


def test_live_context_summary_empty_result():
    out = live_context_summary({"result": ""}, [])
    # Fallback: status + tiles (with empty domain_counts), no section
    assert out[0]["text"].startswith("0 entities")
    assert out[1]["items"] == []


@pytest.mark.parametrize("payload", [
    {"result": 123},            # non-string result → passthrough
    {},                         # missing result → passthrough
])
def test_live_context_summary_bad_input_passthrough(payload):
    # When the payload is unusable, the transform returns the original
    # components list unchanged so the YAML fallback renders.
    sentinel = [{"type": "status", "text": "fallback"}]
    assert live_context_summary(payload, sentinel) == sentinel
