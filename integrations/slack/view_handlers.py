"""Slack view handler — bridges view_submission → server modal waiter.

Bolt delivers ``view_submission`` events when a user submits a modal.
The view's ``callback_id`` matches the one the agent's ``open_modal``
tool registered with ``app.services.modal_waiter``. We forward the
submission to the server via ``POST /api/v1/modals/{callback_id}/submit``;
the waiter resolves and the paused tool call returns.

Bolt also delivers ``view_closed`` when the user dismisses without
submitting; we post to ``/cancel`` so the tool returns a clean "user
dismissed" error instead of timing out.
"""
from __future__ import annotations

import json
import logging
import re

import httpx

from modal_views import values_from_view
from slack_settings import AGENT_BASE_URL, API_KEY

logger = logging.getLogger(__name__)

# Any view with a ``spindrel_modal:`` prefix identifies as ours — we
# prefix all open_modal-driven views so we don't consume modals from
# other Slack apps that happen to share our workspace. The Bolt
# constraint MUST be a regex Pattern: a plain string (including "") is
# matched with exact equality (``input == constraint``), not as a glob,
# so any non-empty real callback_id would silently fail to dispatch.
_CALLBACK_PREFIX = "spindrel_modal:"
_CALLBACK_RE = re.compile(r"^spindrel_modal:")


def register_view_handlers(app) -> None:
    @app.view(_CALLBACK_RE)
    async def on_view_submission(ack, body, view):
        cb = view.get("callback_id") or ""
        await ack()
        if not cb.startswith(_CALLBACK_PREFIX):
            return
        callback_id = cb[len(_CALLBACK_PREFIX):]
        user_id = body.get("user", {}).get("id", "unknown")
        values = values_from_view(view)

        private_metadata_raw = view.get("private_metadata") or ""
        metadata: dict = {}
        channel_id: str | None = None
        if private_metadata_raw:
            try:
                parsed = json.loads(private_metadata_raw)
            except json.JSONDecodeError:
                parsed = {}
            if isinstance(parsed, dict):
                metadata = parsed.get("metadata") or {}
                channel_id = parsed.get("channel_id")

        await _post(
            f"/api/v1/modals/{callback_id}/submit",
            {
                "values": values,
                "submitted_by": user_id,
                "metadata": metadata,
                "channel_id": channel_id,
            },
        )

    @app.view_closed(_CALLBACK_RE)
    async def on_view_closed(ack, view):
        cb = view.get("callback_id") or ""
        await ack()
        if not cb.startswith(_CALLBACK_PREFIX):
            return
        callback_id = cb[len(_CALLBACK_PREFIX):]
        await _post(f"/api/v1/modals/{callback_id}/cancel", {})


async def _post(path: str, body: dict) -> None:
    url = f"{AGENT_BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(url, json=body, headers=headers)
    except Exception:
        logger.warning("view handler POST %s failed", path, exc_info=True)
