from __future__ import annotations

import json

from app.services.widget_preview import render_preview_envelope


def test_render_preview_envelope_applies_transform_without_static_template():
    widget_def = {
        "content_type": "application/vnd.spindrel.components+json",
        "display": "inline",
        "display_label": "{{data.entity_id}}",
        "transform": "integrations.homeassistant.widget_transforms:render_single_entity_widget",
        "default_config": {"preset_variant": "entity_chip"},
    }

    envelope = render_preview_envelope(
        widget_def,
        tool_name="ha_get_state",
        sample_payload={
            "data": {
                "entity_id": "switch.office_light_switch",
                "state": "off",
                "attributes": {
                    "friendly_name": "Office Light Switch",
                },
            },
        },
        widget_config={"preset_variant": "entity_chip", "primary_info": "name", "secondary_info": "none"},
    )

    body = json.loads(envelope.body)
    assert body["v"] == 1
    assert body["components"][0]["type"] == "status"
    assert body["components"][0]["text"] == "Office Light Switch"
