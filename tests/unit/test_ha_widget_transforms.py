"""Unit tests for Home Assistant widget transforms.

Fixtures are real payloads captured from the ha-mcp and official HA MCP
servers — see the haos-bot request trace in the PR description.
"""
from __future__ import annotations

import json

import pytest

from integrations.homeassistant.widget_transforms import (
    live_context_poll,
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
    assert out["widget_variant"] == "sensor_card"
    assert out["supports_toggle"] is False
    assert out["supports_brightness"] is False


def test_single_entity_state_light_on():
    out = single_entity_state(HA_GET_STATE_LIGHT_ON, {})
    assert out["is_on"] is True
    assert out["is_off"] is False
    assert out["domain"] == "light"
    # No unit → state echoed bare
    assert out["display_value"] == "on"
    assert out["widget_variant"] == "light_card"
    assert out["supports_toggle"] is True
    assert out["supports_brightness"] is True
    assert out["show_brightness"] is True
    assert out["brightness"] == 71


def test_single_entity_state_light_hides_brightness_when_config_disabled():
    out = single_entity_state(HA_GET_STATE_LIGHT_ON, {"config": {"show_brightness": False}})
    assert out["supports_brightness"] is True
    assert out["show_brightness"] is False


def test_single_entity_state_toggle_chip_variant():
    payload = json.dumps({
        "data": {
            "entity_id": "switch.espresso_machine",
            "state": "off",
            "attributes": {"friendly_name": "Espresso Machine"},
        },
    })
    out = single_entity_state(payload, {})
    assert out["widget_variant"] == "toggle_chip"
    assert out["supports_toggle"] is True
    assert out["toggle_target_name"] == "Espresso Machine"
    assert out["toggle_on_tool"] == "HassTurnOn"
    assert out["toggle_off_tool"] == "HassTurnOff"


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
        "  areas: Office\n"
        "  attributes:\n"
        "    brightness: '180'\n"
        "- names: Bedroom Lamp\n"
        "  domain: light\n"
        "  state: 'off'\n"
        "  areas: Bedroom\n"
        "- names: Kitchen Temperature Temperature\n"
        "  domain: sensor\n"
        "  state: '71.69'\n"
        "  areas: Kitchen\n"
        "  attributes:\n"
        "    unit_of_measurement: °F\n"
        "- names: Living Room TV\n"
        "  domain: media_player\n"
        "  state: playing\n"
        "  areas: Living Room\n"
        "- names: Front Door\n"
        "  domain: binary_sensor\n"
        "  state: 'off'\n"
    ),
}


def _find(components, node_type, *, label=None):
    for c in components:
        if c.get("type") != node_type:
            continue
        if label is not None and c.get("label") != label:
            continue
        return c
    return None


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


def test_live_context_summary_filter_section_buttons():
    """Unfiltered view should expose one button per area + domain so the
    user can click to filter once pinned.
    """
    out = live_context_summary(GET_LIVE_CONTEXT_RESULT, [])
    filter_section = _find(out, "section", label="Filter")
    assert filter_section is not None
    labels = [c["label"] for c in filter_section["children"] if c.get("type") == "button"]
    # Areas in fixture: Office, Bedroom, Kitchen, Living Room
    assert "Kitchen" in labels
    assert "Living Room" in labels
    # Domains in fixture
    assert "light" in labels
    assert "sensor" in labels
    # Every button dispatches widget_config with a filter config
    for c in filter_section["children"]:
        if c.get("type") == "button":
            assert c["action"]["dispatch"] == "widget_config"
            assert "filter" in c["action"]["config"]


def test_live_context_summary_active_filter_by_area():
    """When config.filter is set, only matching entities remain and a
    Clear-filter button is rendered.
    """
    out = live_context_summary(
        {**GET_LIVE_CONTEXT_RESULT, "config": {"filter": "kitchen"}},
        [],
    )
    status = out[0]
    assert status["type"] == "status"
    assert "Filtered: kitchen" in status["text"]
    assert "1/5" in status["text"]

    clear = _find(out, "button")
    assert clear is not None
    assert clear["label"] == "Clear filter"
    assert clear["action"]["config"] == {"filter": ""}

    # Filter UI itself is hidden once a filter is active
    assert _find(out, "section", label="Filter") is None


def test_live_context_summary_filter_by_domain():
    out = live_context_summary(
        {**GET_LIVE_CONTEXT_RESULT, "config": {"filter": "light"}},
        [],
    )
    assert "2/5" in out[0]["text"]  # two lights


def test_live_context_summary_filter_case_insensitive():
    out_upper = live_context_summary(
        {**GET_LIVE_CONTEXT_RESULT, "config": {"filter": "KITCHEN"}}, [],
    )
    out_lower = live_context_summary(
        {**GET_LIVE_CONTEXT_RESULT, "config": {"filter": "kitchen"}}, [],
    )
    # Both should match the same entity set (count is what matters)
    assert "1/5" in out_upper[0]["text"]
    assert "1/5" in out_lower[0]["text"]


def test_live_context_summary_empty_filter_is_unfiltered():
    out = live_context_summary(
        {**GET_LIVE_CONTEXT_RESULT, "config": {"filter": ""}}, [],
    )
    # Same as no config at all
    baseline = live_context_summary(GET_LIVE_CONTEXT_RESULT, [])
    assert out[0]["text"] == baseline[0]["text"]


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
    assert _find(out, "section", label="Active now (0)") is None
    # "Active now" not in any section's label
    for c in out:
        if c.get("type") == "section":
            assert not c["label"].startswith("Active now")


def test_live_context_summary_empty_result():
    out = live_context_summary({"result": ""}, [])
    # Fallback: status only — no domains → no tiles, no active → no section,
    # no areas/domains → no Filter section.
    assert out[0]["text"].startswith("0 entities")
    assert all(c.get("type") != "tiles" for c in out)


@pytest.mark.parametrize("payload", [
    {"result": 123},            # non-string result → passthrough
    {},                         # missing result → passthrough
])
def test_live_context_summary_bad_input_passthrough(payload):
    # When the payload is unusable, the transform returns the original
    # components list unchanged so the YAML fallback renders.
    sentinel = [{"type": "status", "text": "fallback"}]
    assert live_context_summary(payload, sentinel) == sentinel


# ── Regression: ha_get_state pin wiring ──

def test_ha_get_state_widget_shape_matches_transform_contract():
    """ha_get_state pins now seed config.entity_id at create time, and the
    poll path must read that explicit binding instead of depending on
    display_label hacks forever.
    """
    import yaml

    with open("integrations/homeassistant/integration.yaml") as f:
        doc = yaml.safe_load(f)

    spec = doc["tool_widgets"]["ha_get_state"]
    assert spec["display_label"] == "{{data.entity_id}}"
    assert spec["state_poll"]["args"]["entity_id"] == "{{config.entity_id}}"
    assert spec["default_config"]["show_brightness"] is True


def test_live_context_poll_returns_data_dict_for_each_block_template():
    """The state_poll template uses each-blocks over area_buttons /
    domain_buttons — the poll transform must expose those as lists of
    dicts with `label` + `filter_value` keys so the each-expansion can
    produce valid button components.
    """
    out = live_context_poll(
        json.dumps(GET_LIVE_CONTEXT_RESULT),
        {"config": {"filter": ""}, "display_label": "whatever", "tool_name": "GetLiveContext"},
    )
    assert out["filter_active"] is False
    for key in ("area_buttons", "domain_buttons"):
        assert isinstance(out[key], list)
        for b in out[key]:
            assert "label" in b and "filter_value" in b
    # An active filter should suppress the button lists in the template
    # via {{filter_active | not}}, but the data shape is the same.
    out2 = live_context_poll(
        json.dumps(GET_LIVE_CONTEXT_RESULT),
        {"config": {"filter": "kitchen"}},
    )
    assert out2["filter_active"] is True
    assert "Filtered: kitchen" in out2["status_text"]
    assert "1/5" in out2["status_text"]


def test_get_live_context_widget_has_state_poll_wired():
    """The filter buttons are useless without a state_poll — clicking
    them hits _dispatch_widget_config which returns envelope=None when
    no state_poll is configured (see app/routers/api_v1_widget_actions.py).
    """
    import yaml
    with open("integrations/homeassistant/integration.yaml") as f:
        spec = yaml.safe_load(f)["tool_widgets"]["GetLiveContext"]
    assert "state_poll" in spec
    assert spec["state_poll"]["tool"] == "GetLiveContext"
    assert spec["state_poll"]["transform"].endswith(":live_context_poll")


def test_single_entity_state_via_state_poll_contract():
    """Smoke test: a state_poll refresh call should produce a fully
    populated dict that the state_poll template can render without
    leaving `{{entity_id}}` / `{{last_changed}}` blank.
    """
    out = single_entity_state(HA_GET_STATE_TEMPERATURE, {
        "display_label": "sensor.kitchen_temperature_temperature",
        "tool_name": "ha_get_state",
        "config": {},
    })
    # Every field the state_poll template references must be non-empty
    # for the rendered properties/status/heading to display.
    for key in ("entity_id", "friendly_name", "display_value", "last_changed"):
        assert out.get(key), f"{key} must be populated for state_poll render"
