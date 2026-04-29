"""Dashboard pin config-editor screenshot stager."""
from __future__ import annotations

from . import StagedState
from . import bots as bot_scenarios
from . import dashboards as dashboard_scenarios
from .. import envelopes as env
from ..client import SpindrelClient


DASHBOARD_PIN_CONFIG_CLIENT_ID = "screenshot:dashboard-pin-config-editor"
CONFIG_PIN_LABEL = "Configurable status"


def stage_dashboard_pin_config_editor(
    client: SpindrelClient,
    *,
    dry_run: bool = False,
    **_unused,
) -> StagedState:
    state = StagedState()
    if dry_run:
        state.channels["dashboard_pin_config_channel"] = "dry-run-dashboard-pin-config"
        state.pins["dashboard_pin_config_pin"] = "dry-run-config-pin"
        return state

    bot_ids = bot_scenarios.ensure_demo_bots(client)
    bot_id = bot_ids[0]
    channel = client.ensure_channel(
        client_id=DASHBOARD_PIN_CONFIG_CLIENT_ID,
        bot_id=bot_id,
        name="Widget config editor",
        category="Showcase",
    )
    channel_id = str(channel["id"])

    dashboard_key = dashboard_scenarios.dashboard_key_for_channel(channel_id)
    existing = {
        str(pin.get("display_label") or ""): pin
        for pin in client.list_pins(dashboard_key=dashboard_key)
    }
    pin = existing.get(CONFIG_PIN_LABEL)
    if pin and pin.get("id"):
        pin_id = str(pin["id"])
        client.patch_pins_layout(
            dashboard_key=dashboard_key,
            items=[{"id": pin_id, "zone": "grid", "x": 0, "y": 0, "w": 6, "h": 12}],
        )
    else:
        pin = client.create_pin(
            dashboard_key=dashboard_key,
            tool_name="notes_native",
            envelope=env.notes(),
            source_kind="channel",
            source_channel_id=channel_id,
            source_bot_id=bot_id,
            display_label=CONFIG_PIN_LABEL,
            zone="grid",
            grid_layout={"x": 0, "y": 0, "w": 6, "h": 12},
            widget_config={
                "entity_id": "sensor.front_door",
                "units": "imperial",
                "compact": False,
                "refresh_interval": 60,
            },
        )
        pin_id = str(pin["id"])

    state.channels["dashboard_pin_config_channel"] = channel_id
    state.bots["dashboard_pin_config_bot"] = bot_id
    state.pins["dashboard_pin_config_pin"] = pin_id
    state.dashboards["dashboard_pin_config_dashboard"] = dashboard_key
    return state


def teardown_dashboard_pin_config_editor(client: SpindrelClient) -> None:
    for ch in client.list_channels():
        if ch.get("client_id") == DASHBOARD_PIN_CONFIG_CLIENT_ID:
            client.delete_channel(str(ch["id"]))
