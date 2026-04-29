"""Channel session-tabs screenshot stager."""
from __future__ import annotations

from . import StagedState
from . import bots as bot_scenarios
from .core_features import KB_BOT_ID
from .._exec import run_server_helper
from ..client import SpindrelClient

CHANNEL_SESSION_TABS_CLIENT_ID = "screenshot:channel-session-tabs"
CHANNEL_SESSION_TABS_FILE_PATH = "notes/session-tab-workflow.md"


def stage_channel_session_tabs(
    client: SpindrelClient,
    *,
    ssh_alias: str,
    ssh_container: str,
    dry_run: bool = False,
    **_unused,
) -> StagedState:
    state = StagedState()
    if dry_run:
        state.channels["channel_session_tabs"] = "dry-run-channel-session-tabs"
        return state

    bot_scenarios.ensure_demo_bots(client)
    channel = client.ensure_channel(
        client_id=CHANNEL_SESSION_TABS_CLIENT_ID,
        bot_id=KB_BOT_ID,
        name="Session tabs demo",
        category="Showcase",
    )
    channel_id = str(channel["id"])

    # Preserve three normal channel sessions. ``reset_channel`` starts a new
    # primary session without deleting the previous one; the helper gives each
    # session real visible transcript content so the catalog has previews.
    for _ in range(3):
        client.reset_channel(channel_id)
        run_server_helper(
            ssh_alias=ssh_alias,
            container=ssh_container,
            helper_name="seed_chat_messages",
            args=[channel_id, KB_BOT_ID],
            dry_run=dry_run,
        )

    client.write_channel_workspace_file(
        channel_id,
        CHANNEL_SESSION_TABS_FILE_PATH,
        (
            "# Session tab workflow\n\n"
            "A file opens into the same low-chrome tab strip as recent sessions.\n\n"
            "- Selecting an open file tab should not reorder the strip.\n"
            "- Split right is an explicit tab action.\n"
        ),
    )
    state.channels["channel_session_tabs"] = channel_id
    state.bots["channel_session_tabs"] = KB_BOT_ID
    return state


def teardown_channel_session_tabs(client: SpindrelClient) -> None:
    for ch in client.list_channels():
        if ch.get("client_id") == CHANNEL_SESSION_TABS_CLIENT_ID:
            client.delete_channel(str(ch["id"]))
