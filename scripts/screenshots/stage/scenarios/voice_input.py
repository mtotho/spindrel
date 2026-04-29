"""Voice-input screenshot stager."""

from __future__ import annotations

from . import StagedState
from . import bots as bot_scenarios
from .core_features import KB_BOT_ID, _ensure_chat_content_bots
from ..client import SpindrelClient

VOICE_INPUT_CHANNEL_CLIENT_ID = "screenshot:voice-input"


def stage_voice_input(client: SpindrelClient, *, dry_run: bool = False, **_unused) -> StagedState:
    state = StagedState()
    if dry_run:
        state.channels["voice_input"] = "dry-run-voice-input-channel"
        return state

    bot_scenarios.ensure_demo_bots(client)
    _ensure_chat_content_bots(client)
    channel = client.ensure_channel(
        client_id=VOICE_INPUT_CHANNEL_CLIENT_ID,
        bot_id=KB_BOT_ID,
        name="Voice input demo",
        category="Showcase",
    )
    channel_id = str(channel["id"])
    client.reset_channel(channel_id)
    state.channels["voice_input"] = channel_id
    state.bots["voice_input"] = KB_BOT_ID
    return state


def teardown_voice_input(client: SpindrelClient) -> None:
    for ch in client.list_channels():
        if ch.get("client_id") == VOICE_INPUT_CHANNEL_CLIENT_ID:
            client.delete_channel(str(ch["id"]))
