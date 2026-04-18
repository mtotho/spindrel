"""The ``open_modal:<callback_id>`` button action — opens a Block Kit modal.

The agent's ``open_modal`` tool posts a message to the channel with an
inline button whose ``value`` carries a JSON blob ``{schema, title, submit_label}``.
When the user clicks, this handler decodes the blob and calls
``views.open`` with a fresh ``trigger_id`` — the only Slack-supplied
handle short-lived enough to open a modal mid-conversation.

Callback ids on the resulting view carry our ``spindrel_modal:`` prefix
so ``view_handlers.py`` can distinguish our submissions from any other
app's modals sharing the workspace.
"""
from __future__ import annotations

import json
import logging
import re

from modal_views import schema_to_view

logger = logging.getLogger(__name__)

_ACTION_PATTERN = re.compile(r"^open_modal:(?P<cb>[A-Za-z0-9_\-\.]+)$")

# Must match view_handlers._CALLBACK_PREFIX
_CALLBACK_PREFIX = "spindrel_modal:"


def register_modal_action_handler(app) -> None:
    @app.action(_ACTION_PATTERN)
    async def on_open_modal(ack, body, client):
        await ack()
        action = (body.get("actions") or [{}])[0]
        value_raw = action.get("value") or ""
        try:
            payload = json.loads(value_raw)
        except json.JSONDecodeError:
            logger.debug("open_modal button value was not valid JSON")
            return
        if not isinstance(payload, dict):
            return

        callback_id = payload.get("callback_id") or ""
        schema = payload.get("schema") or {}
        title = payload.get("title") or "Form"
        submit_label = payload.get("submit_label") or "Submit"
        metadata = payload.get("metadata") or {}
        channel_id = (body.get("channel") or {}).get("id") or ""

        if not callback_id or not schema:
            return

        trigger_id = body.get("trigger_id")
        if not trigger_id:
            return

        view = schema_to_view(
            callback_id=f"{_CALLBACK_PREFIX}{callback_id}",
            title=title,
            schema=schema,
            submit_label=submit_label,
            private_metadata=json.dumps(
                {"metadata": metadata, "channel_id": channel_id}
            ),
        )
        try:
            await client.views_open(trigger_id=trigger_id, view=view)
        except Exception:
            logger.warning(
                "views.open failed for callback_id=%s", callback_id, exc_info=True,
            )
