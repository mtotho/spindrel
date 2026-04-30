from __future__ import annotations

from pathlib import Path

import yaml

from integrations.unifi.bindings import network_options, site_options


def test_manifest_declares_tools_skill_router_and_widget_presets() -> None:
    manifest = yaml.safe_load(Path("integrations/unifi/integration.yaml").read_text())

    assert manifest["id"] == "unifi"
    assert "router" in manifest["provides"]
    assert "tools" in manifest["provides"]
    assert "skills" in manifest["provides"]
    assert manifest["debug_actions"][0]["endpoint"] == "diagnose"
    assert "unifi_vlan_advisor" in manifest["tool_families"]["unifi"]["tools"]
    assert set(manifest["widget_presets"]) == {
        "unifi-connection-diagnostics",
        "unifi-network-health",
        "unifi-vlan-map",
        "unifi-devices-card",
        "unifi-clients-card",
    }
    assert "unifi_network_snapshot" in manifest["tool_widgets"]
    assert "unifi_vlan_advisor" in manifest["tool_widgets"]


def test_site_options_binding_transform() -> None:
    raw = '{"sites": [{"site": "default", "label": "Default"}]}'

    assert site_options(raw, {}) == [{
        "value": "default",
        "label": "Default",
        "description": "UniFi site",
        "group": "Sites",
        "meta": {"site_id": "default"},
    }]


def test_network_options_binding_transform() -> None:
    raw = '{"networks": [{"id": "iot", "name": "IoT", "vlanId": 30}]}'

    assert network_options(raw, {}) == [{
        "value": "iot",
        "label": "IoT",
        "description": "VLAN 30",
        "group": "Networks",
        "meta": {"vlan": "30"},
    }]


def test_skill_is_troubleshooting_focused_and_read_only() -> None:
    body = Path("integrations/unifi/skills/unifi_network.md").read_text()

    assert "Start with tools before advice" in body
    assert "unifi_vlan_advisor" in body
    assert "DHCP" in body
    assert "VLAN Viewer" in body
    assert "Do not claim you can change UniFi config" in body

