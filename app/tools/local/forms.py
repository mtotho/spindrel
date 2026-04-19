"""Agent tool — open_modal: collect structured input from the user.

Flow (Slack; the only integration with the ``MODALS`` capability today):

1. Tool resolves the channel's bindings via ``dispatch_resolution.
   resolve_targets``. It picks the binding that natively owns the
   triggering user's surface — the integration whose "source" matches
   the last inbound user message on the channel (see
   ``Message.metadata["source"]``). If no MODALS-capable binding
   exists — or if the origin binding lacks MODALS — the tool returns
   ``unsupported`` and the agent should fall back to asking the user
   conversationally instead.

2. Tool generates a ``callback_id`` and registers a waiter in
   ``app.services.modal_waiter``.

3. Tool posts a channel message carrying an inline "Open form" button
   **scoped to the target binding only** via
   ``outbox_publish.enqueue_new_message_for_target``. Other bindings on
   the same channel (web, etc.) never receive the button — they would
   render a dead-end since the action handler is integration-native.

4. User clicks the button. The Slack subprocess action handler at
   ``integrations/slack/modal_action_handler.py`` calls ``views.open``.

5. User submits. ``integrations/slack/view_handlers.py`` posts values
   to ``POST /api/v1/modals/{callback_id}/submit`` which resolves the
   waiter.

Phase C's capability-gated tool exposure keeps this tool out of the
LLM's tool list entirely on channels with no MODALS-capable binding,
so the unsupported path is a last-line defense, not the common case.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.agent.context import current_bot_id, current_channel_id, current_session_id
from app.db.engine import async_session
from app.db.models import Channel, Message as MessageRow
from app.domain.actor import ActorRef
from app.domain.capability import Capability
from app.domain.message import Message as DomainMessage
from app.integrations import renderer_registry
from app.services import modal_waiter
from app.services.dispatch_resolution import resolve_targets
from app.services.outbox_publish import enqueue_new_message_for_target
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
            "the user dismisses the form or no bound integration on this "
            "channel supports modals."
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
}, safety_tier="readonly", required_capabilities=frozenset({Capability.MODALS}), requires_bot_context=True, requires_channel_context=True)
async def open_modal(
    title: str,
    schema: dict,
    submit_label: str = "Submit",
    prompt: str = "",
) -> str:
    channel_id = current_channel_id.get()
    if channel_id is None:
        return json.dumps({"ok": False, "error": "no channel in current context"})

    target_integration_id = await _pick_modal_target(channel_id)
    if target_integration_id is None:
        return json.dumps({
            "ok": False,
            "error": (
                "no bound integration on this channel supports modals — "
                "ask the user conversationally for these fields instead"
            ),
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

    try:
        await _post_open_modal_button(
            integration_id=target_integration_id,
            channel_id=channel_id,
            callback_id=callback_id,
            button_value=button_value,
            prompt=prompt or f"Click to open the form: *{title}*",
        )
    except Exception as exc:
        # Don't leave the waiter dangling — the user will never see a
        # button to click, so blocking 15 min on the wait is just dead
        # time before the agent gets to react to the failure.
        modal_waiter.cancel(callback_id, reason=f"post_failed: {exc}")
        await modal_waiter.wait(callback_id, timeout=0.1)
        return json.dumps({"ok": False, "error": f"failed to post modal button: {exc}"})

    result = await modal_waiter.wait(callback_id, timeout=_MODAL_TIMEOUT_SECONDS)
    return json.dumps(result)


async def _pick_modal_target(channel_id: uuid.UUID) -> str | None:
    """Choose the binding to open the modal on, or None if impossible.

    Preference order:
      1. The binding whose ``integration_id`` matches the last inbound
         user message's ``metadata["source"]`` on this channel — the
         user is already on that surface; opening the modal there is
         the only option Slack's ``trigger_id`` window accepts anyway.
      2. Any other MODALS-capable binding on the channel.
      3. None if no bound integration has ``Capability.MODALS``.
    """
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if channel is None:
            return None
        origin = await _last_user_message_source(db, channel_id)

    targets = await resolve_targets(channel)
    modals_capable = [
        integration_id for integration_id, _t in targets
        if _renderer_has_modals(integration_id)
    ]
    if not modals_capable:
        return None
    if origin and origin in modals_capable:
        return origin
    return modals_capable[0]


def _renderer_has_modals(integration_id: str) -> bool:
    renderer = renderer_registry.get(integration_id)
    if renderer is None:
        return False
    return Capability.MODALS in getattr(renderer, "capabilities", frozenset())


async def _last_user_message_source(db, channel_id: uuid.UUID) -> str | None:
    """Look up the last user-role message's ``metadata["source"]`` on this channel.

    Walks the channel's active session first (hot path — same session as
    the current turn) and only falls back to a channel-wide scan if the
    session lookup yields no user message with a ``source`` set.
    """
    session_id = current_session_id.get()
    if session_id is not None:
        row = (
            await db.execute(
                select(MessageRow)
                .where(MessageRow.session_id == session_id)
                .where(MessageRow.role == "user")
                .order_by(MessageRow.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is not None:
            source = (row.metadata_ or {}).get("source")
            if source:
                return source
    return None


async def _post_open_modal_button(
    *,
    integration_id: str,
    channel_id,
    callback_id: str,
    button_value: str,
    prompt: str,
) -> None:
    """Post the Open-Form button as a NEW_MESSAGE scoped to ``integration_id``.

    We persist the prompt message for audit, but enqueue the outbox row
    only for the target integration. Other bindings on the same channel
    never see this message — they would render a dead-end button since
    the action handler is integration-native.
    """
    if not _renderer_has_modals(integration_id):
        # Defensive: caller already picked via _pick_modal_target, but
        # guard in case the renderer registry shifts between calls.
        raise RuntimeError(f"integration {integration_id!r} lacks MODALS capability")

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
            from app.db.models import Session as SessionRow
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
                "target_integration": integration_id,
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
                "target_integration": integration_id,
                "slack_blocks": blocks,
                "slack_button_action": f"open_modal:{callback_id}",
            },
            channel_id=channel_id,
        )

    await enqueue_new_message_for_target(channel_id, domain_msg, integration_id)
