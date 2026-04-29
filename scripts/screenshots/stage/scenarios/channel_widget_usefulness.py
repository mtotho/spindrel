"""Channel widget-usefulness screenshot stager."""
from __future__ import annotations

from . import StagedState
from . import bots as bot_scenarios
from . import dashboards as dashboard_scenarios
from .. import envelopes as env
from ..client import SpindrelClient


CHANNEL_WIDGET_USEFULNESS_CLIENT_ID = "screenshot:channel-widget-usefulness"


def stage_channel_widget_usefulness(
    client: SpindrelClient,
    *,
    dry_run: bool = False,
    **_unused,
) -> StagedState:
    state = StagedState()
    if dry_run:
        state.channels["channel_widget_usefulness"] = "dry-run-channel-widget-usefulness"
        return state

    bot_ids = bot_scenarios.ensure_demo_bots(client)
    bot_id = bot_ids[0]
    channel = client.ensure_channel(
        client_id=CHANNEL_WIDGET_USEFULNESS_CLIENT_ID,
        bot_id=bot_id,
        name="Widget usefulness review",
        category="Showcase",
    )
    channel_id = str(channel["id"])
    client.update_channel_settings(channel_id, layout_mode="rail-chat")

    dashboard_key = dashboard_scenarios.dashboard_key_for_channel(channel_id)
    expected_labels = {
        "Usefulness notes",
        "Usefulness notes copy",
        "Usefulness dock panel",
    }
    for pin in client.list_pins(dashboard_key=dashboard_key):
        label = str(pin.get("display_label") or "")
        if label.startswith("Usefulness ") and label not in expected_labels and pin.get("id"):
            client.delete_pin(str(pin["id"]))

    existing = {
        str(pin.get("display_label") or ""): pin
        for pin in client.list_pins(dashboard_key=dashboard_key)
    }
    specs = [
        ("Usefulness notes", env.notes(), "grid", {"x": 0, "y": 0, "w": 6, "h": 12}),
        ("Usefulness notes copy", env.notes(), "grid", {"x": 6, "y": 0, "w": 6, "h": 12}),
        ("Usefulness dock panel", env.todos(), "dock", {"x": 0, "y": 0, "w": 1, "h": 14}),
    ]
    layout_patches: list[dict] = []
    for label, envelope, zone, grid in specs:
        pin = existing.get(label)
        if pin and pin.get("id"):
            layout_patches.append({"id": str(pin["id"]), "zone": zone, **grid})
            continue
        client.create_pin(
            dashboard_key=dashboard_key,
            tool_name=envelope["body"]["widget_ref"].split("/", 1)[-1],
            envelope=envelope,
            source_kind="channel",
            source_channel_id=channel_id,
            source_bot_id=bot_id,
            display_label=label,
            zone=zone,
            grid_layout=grid,
        )
    if layout_patches:
        client.patch_pins_layout(dashboard_key=dashboard_key, items=layout_patches)

    state.channels["channel_widget_usefulness"] = channel_id
    state.bots["channel_widget_usefulness"] = bot_id
    state.dashboards["channel_widget_usefulness"] = dashboard_key
    return state


def teardown_channel_widget_usefulness(client: SpindrelClient) -> None:
    for ch in client.list_channels():
        if ch.get("client_id") == CHANNEL_WIDGET_USEFULNESS_CLIENT_ID:
            client.delete_channel(str(ch["id"]))
