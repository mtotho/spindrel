"""Agent tool — open_modal: collect structured input from the user.

Flow (Slack; other integrations fall back to conversational Q&A):

1. Tool generates a ``callback_id`` and registers a waiter in
   ``app.services.modal_waiter``.
2. Tool posts a channel message via the Slack renderer's button path —
   the message holds an inline button whose ``value`` carries the JSON
   schema. (Slack restricts modals to opens driven by a fresh
   ``trigger_id``; the button click provides one.)
3. User clicks the button; the Slack subprocess action handler at
   ``integrations/slack/modal_action_handler.py`` calls ``views.open``.
4. User submits; ``integrations/slack/view_handlers.py`` posts the
   values to ``POST /api/v1/modals/{callback_id}/submit``.
5. ``modal_waiter.wait`` returns; the tool returns the values to the
   agent.

On integrations without the ``MODALS`` capability, this tool
short-circuits with an informative error — the calling agent should
then ask the user conversationally instead. The expected fallback is
covered by the integration depth playbook.
"""
from __future__ import annotations

import json
import uuid

from app.agent.context import current_channel_id
from app.domain.capability import Capability
from app.integrations import renderer_registry
from app.services import modal_waiter
from app.services.ephemeral_dispatch import _resolve_integration_id
from app.tools.registry import register

# Max size of the inline button value — Slack enforces 2000 chars.
_MAX_VALUE_BYTES = 1900
# Max time to wait for a submission; keeps long-running turns bounded.
_MODAL_TIMEOUT_SECONDS = 15 * 60


@register({
    "type": "function",
    "function": {
        "name": "open_modal",
        "description": (
            "Open a form (modal) in the user's current channel and wait "
            "for them to submit. Use for structured input that's awkward "
            "to collect conversationally — e.g. filing a bug, booking a "
            "resource, multi-field configuration. Returns the submitted "
            "values as a JSON object keyed by field id, or an error if "
            "the user dismisses the form or the integration does not "
            "support modals."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Modal header — short (≤ 24 chars).",
                },
                "schema": {
                    "type": "object",
                    "description": (
                        "Fields keyed by id. Each value has {type, label, "
                        "required?, placeholder?, choices?}. Supported types: "
                        "'text', 'textarea', 'select', 'url', 'number', 'date'."
                    ),
                },
                "submit_label": {
                    "type": "string",
                    "description": "Submit button label (default: 'Submit').",
                },
                "prompt": {
                    "type": "string",
                    "description": (
                        "Short intro message displayed alongside the 'Open form' "
                        "button so the user knows what they're about to fill."
                    ),
                },
            },
            "required": ["title", "schema"],
        },
    },
}, safety_tier="readonly")
async def open_modal(
    title: str,
    schema: dict,
    submit_label: str = "Submit",
    prompt: str = "",
) -> str:
    channel_id = current_channel_id.get()
    if channel_id is None:
        return json.dumps({"ok": False, "error": "no channel in current context"})

    integration_id = await _resolve_integration_id(channel_id)
    if integration_id is None:
        return json.dumps({"ok": False, "error": "channel not bound to an integration"})

    renderer = renderer_registry.get(integration_id)
    supports_modals = bool(
        renderer and Capability.MODALS in getattr(renderer, "capabilities", frozenset())
    )
    if not supports_modals:
        return json.dumps({
            "ok": False,
            "error": f"integration '{integration_id}' does not support modals — "
                     f"ask the user conversationally for these fields instead",
            "unsupported": True,
        })

    callback_id = str(uuid.uuid4())
    modal_waiter.register(callback_id)

    button_value = json.dumps({
        "callback_id": callback_id,
        "title": title[:24],
        "schema": schema,
        "submit_label": submit_label[:24],
        "metadata": {"channel_id": str(channel_id)},
    })
    if len(button_value) > _MAX_VALUE_BYTES:
        modal_waiter.cancel(callback_id, reason="schema_too_large")
        await modal_waiter.wait(callback_id, timeout=0.1)  # drain the slot
        return json.dumps({
            "ok": False,
            "error": (
                f"schema too large for Slack button value "
                f"({len(button_value)} > {_MAX_VALUE_BYTES} bytes) — "
                f"split the form or reduce choice lists"
            ),
        })

    await _post_open_modal_button(
        integration_id=integration_id,
        channel_id=channel_id,
        callback_id=callback_id,
        button_value=button_value,
        prompt=prompt or f"Click to open the form: *{title}*",
    )

    result = await modal_waiter.wait(callback_id, timeout=_MODAL_TIMEOUT_SECONDS)
    return json.dumps(result)


async def _post_open_modal_button(
    *,
    integration_id: str,
    channel_id,
    callback_id: str,
    button_value: str,
    prompt: str,
) -> None:
    """Emit a NEW_MESSAGE carrying an Open-Form button.

    Slack is the only integration with the MODALS capability today; we
    build the Block Kit block inline. Future integrations plug in by
    implementing their own renderer branch for ``OpenModal`` actions —
    a richer design could route through ``handle_outbound_action`` but
    that requires wiring the agent loop's action-emission path. Phase 4
    uses the simpler "post a message with a button" approach so the
    existing NEW_MESSAGE delivery path handles delivery, persistence,
    and Slack echo filtering for free.
    """
    if integration_id != "slack":
        # Other integrations: noop for now (MODALS capability is gated
        # above, so we never reach here in practice).
        return

    from datetime import datetime, timezone
    from app.agent.context import current_bot_id, current_session_id
    from app.db.engine import async_session
    from app.db.models import Message as MessageRow, Session as SessionRow
    from app.domain.actor import ActorRef
    from app.domain.channel_events import ChannelEvent, ChannelEventKind
    from app.domain.message import Message as DomainMessage
    from app.domain.payloads import MessagePayload
    from app.services.channel_events import publish_typed
    from app.services.outbox_publish import enqueue_new_message_for_channel
    from sqlalchemy import select

    bot_id = current_bot_id.get() or ""
    session_uuid = current_session_id.get()
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": prompt}},
        {
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "Open form"},
                "style": "primary",
                "action_id": f"open_modal:{callback_id}",
                "value": button_value,
            }],
        },
    ]

    async with async_session() as db:
        if session_uuid is None:
            latest = (
                await db.execute(
                    select(SessionRow)
                    .where(SessionRow.channel_id == channel_id)
                    .order_by(SessionRow.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if latest is None:
                return
            session_uuid = latest.id

        row = MessageRow(
            session_id=session_uuid,
            role="assistant",
            content=prompt,
            metadata_={
                "source": "open_modal",
                "bot_id": bot_id,
                "slack_blocks": blocks,
                "slack_button_action": f"open_modal:{callback_id}",
            },
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        domain_msg = DomainMessage(
            id=row.id,
            session_id=session_uuid,
            role="assistant",
            content=prompt,
            created_at=row.created_at or datetime.now(timezone.utc),
            actor=ActorRef.bot(bot_id or "bot"),
            metadata={
                "source": "open_modal",
                "slack_blocks": blocks,
                "slack_button_action": f"open_modal:{callback_id}",
            },
            channel_id=channel_id,
        )

    await enqueue_new_message_for_channel(channel_id, domain_msg)
    publish_typed(
        channel_id,
        ChannelEvent(
            channel_id=channel_id,
            kind=ChannelEventKind.NEW_MESSAGE,
            payload=MessagePayload(message=domain_msg),
        ),
    )
