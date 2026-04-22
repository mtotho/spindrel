from app.services.dashboard_pins import _seed_widget_config


def test_seed_widget_config_ha_get_state_uses_display_label_entity_id():
    out = _seed_widget_config(
        "ha_get_state",
        {"display_label": "light.office_desk_led_strip"},
        None,
    )
    assert out == {"entity_id": "light.office_desk_led_strip"}


def test_seed_widget_config_preserves_existing_entity_id():
    out = _seed_widget_config(
        "ha_get_state",
        {"display_label": "light.office_desk_led_strip"},
        {"entity_id": "switch.espresso_machine", "show_brightness": False},
    )
    assert out == {
        "entity_id": "switch.espresso_machine",
        "show_brightness": False,
    }
