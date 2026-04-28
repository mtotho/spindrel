"""Attachment-handling screenshot stager.

Creates a single clean channel for browser-driven composer upload captures.
The actual files are dropped by Playwright in the capture specs so the
screenshots exercise the real frontend routing/upload path.
"""
from __future__ import annotations

import logging

from . import StagedState
from . import bots as bot_scenarios
from .core_features import KB_BOT_ID, _ensure_chat_content_bots
from ..client import SpindrelClient

logger = logging.getLogger(__name__)

ATTACHMENT_CHANNEL_CLIENT_ID = "screenshot:attachments"


def _clear_upload_debris(client: SpindrelClient, channel_id: str) -> None:
    """Delete prior attachment-check uploads so reruns stay visually stable."""
    try:
        files = client.list_channel_workspace_files(
            channel_id,
            include_data=True,
            data_prefix="uploads",
        )
    except Exception:
        logger.exception("attachment stager: failed to list prior uploads")
        return
    for item in files:
        path = str(item.get("path") or "")
        if not path.startswith("data/uploads/"):
            continue
        try:
            client.delete_channel_workspace_file(channel_id, path)
        except Exception:
            logger.warning("attachment stager: failed to delete %s", path, exc_info=True)


def stage_attachments(client: SpindrelClient, *, dry_run: bool = False, **_unused) -> StagedState:
    state = StagedState()
    if dry_run:
        state.channels["attachments"] = "dry-run-attachments-channel"
        return state

    bot_scenarios.ensure_demo_bots(client)
    _ensure_chat_content_bots(client)

    channel = client.ensure_channel(
        client_id=ATTACHMENT_CHANNEL_CLIENT_ID,
        bot_id=KB_BOT_ID,
        name="Attachment handling demo",
        category="Showcase",
    )
    channel_id = str(channel["id"])
    client.reset_channel(channel_id)
    _clear_upload_debris(client, channel_id)
    state.channels["attachments"] = channel_id
    state.bots["attachments"] = KB_BOT_ID
    return state


def teardown_attachments(client: SpindrelClient) -> None:
    for ch in client.list_channels():
        if ch.get("client_id") == ATTACHMENT_CHANNEL_CLIENT_ID:
            try:
                _clear_upload_debris(client, str(ch["id"]))
            finally:
                client.delete_channel(str(ch["id"]))
