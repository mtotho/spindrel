"""Channel quick-automations screenshot stager."""
from __future__ import annotations

from . import StagedState
from . import bots as bot_scenarios
from .core_features import KB_BOT_ID
from ..client import SpindrelClient

CHANNEL_QUICK_AUTOMATIONS_CLIENT_ID = "screenshot:channel-quick-automations"


def stage_channel_quick_automations(
    client: SpindrelClient,
    *,
    dry_run: bool = False,
    **_unused,
) -> StagedState:
    state = StagedState()
    if dry_run:
        state.channels["channel_quick_automations"] = "dry-run-channel-quick-automations"
        return state

    bot_scenarios.ensure_demo_bots(client)
    channel = client.ensure_channel(
        client_id=CHANNEL_QUICK_AUTOMATIONS_CLIENT_ID,
        bot_id=KB_BOT_ID,
        name="Quick automations demo",
        category="Showcase",
    )

    state.channels["channel_quick_automations"] = str(channel["id"])
    state.bots["channel_quick_automations"] = KB_BOT_ID
    return state


def teardown_channel_quick_automations(client: SpindrelClient) -> None:
    for ch in client.list_channels():
        if ch.get("client_id") == CHANNEL_QUICK_AUTOMATIONS_CLIENT_ID:
            client.delete_channel(str(ch["id"]))
