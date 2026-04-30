from __future__ import annotations

from pathlib import Path

import yaml

from integrations.truenas.bindings import pool_options


def test_manifest_declares_tools_skill_and_widget_presets() -> None:
    manifest = yaml.safe_load(Path("integrations/truenas/integration.yaml").read_text())

    assert manifest["id"] == "truenas"
    assert "router" in manifest["provides"]
    assert "tools" in manifest["provides"]
    assert "skills" in manifest["provides"]
    assert manifest["debug_actions"][0]["endpoint"] == "diagnose"
    assert "truenas_health_snapshot" in manifest["tool_families"]["truenas"]["tools"]
    assert set(manifest["widget_presets"]) == {
        "truenas-health-overview",
        "truenas-connection-diagnostics",
        "truenas-pool-card",
        "truenas-alerts-card",
        "truenas-jobs-card",
    }
    assert "truenas_health_snapshot" in manifest["tool_widgets"]
    assert "truenas_test_connection" in manifest["tool_widgets"]


def test_pool_options_binding_transform() -> None:
    raw = '{"pools": [{"pool": "tank", "state": "ONLINE"}, {"name": "backup", "state": "DEGRADED"}]}'

    assert pool_options(raw, {}) == [
        {
            "value": "tank",
            "label": "tank",
            "description": "ONLINE",
            "group": "Pools",
            "meta": {"state": "ONLINE"},
        },
        {
            "value": "backup",
            "label": "backup",
            "description": "DEGRADED",
            "group": "Pools",
            "meta": {"state": "DEGRADED"},
        },
    ]
