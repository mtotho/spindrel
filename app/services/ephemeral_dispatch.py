"""Publisher-side ephemeral dispatch — strict-deliver, no broadcast fallback.

The agent's ``respond_privately`` tool calls ``deliver_ephemeral`` below.

Contract:

- Channels have zero, one, or many integration bindings (resolved via
  ``app.services.dispatch_resolution.resolve_targets``). Each bound
  renderer either declares ``Capability.EPHEMERAL`` or it does not.

- We publish ``EPHEMERAL_MESSAGE`` scoped to the **single** bound
  integration whose renderer has ``EPHEMERAL`` and which natively owns
  the recipient user id. ``IntegrationDispatcherTask._dispatch`` sees
  the scoped target and silently drops the event on every other
  renderer.

- If no bound integration can deliver the message privately, the tool
  returns ``{"mode": "unsupported"}``. **We never broadcast.** The prior
  "degraded broadcast" path re-published the private text as a public
  ``NEW_MESSAGE`` with a visibility marker — that leaked the content to
  everyone in the channel. It is gone.

The caller (``respond_privately``) is expected to fall back to asking
the user conversationally if this returns unsupported.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.agent.context import current_session_id
from app.db.engine import async_session
from app.db.models import Channel
from app.domain.actor import ActorRef
from app.domain.capability import Capability
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.message import Message
from app.domain.payloads import EphemeralMessagePayload
from app.integrations import renderer_registry
from app.services.channel_events import publish_typed
from app.services.dispatch_resolution import resolve_targets

logger = logging.getLogger(__name__)


async def deliver_ephemeral(
    *,
    channel_id: uuid.UUID,
    bot_id: str,
    recipient_user_id: str,
    text: str,
) -> dict:
    """Deliver a private message to one user on this channel, strict-deliver.

    Returns a dict describing the outcome. ``mode`` is always one of:

    - ``"ephemeral"`` — published ``EPHEMERAL_MESSAGE`` scoped to a
      single integration whose renderer has ``EPHEMERAL`` and which
      natively owns the recipient.
    - ``"unsupported"`` — no bound integration on this channel can
      deliver privately to that recipient. Caller should ask the user
      conversationally instead. No message was sent.
    - ``"error"`` — an unexpected problem occurred (e.g. channel not
      found, bus publish failure).

    Never raises; never falls back to a channel broadcast.
    """
    if not text or not text.strip():
        return {"mode": "error", "error": "empty ephemeral message"}

    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
    if channel is None:
        return {"mode": "error", "error": f"channel {channel_id} not found"}

    targets = await resolve_targets(channel)
    target_integration_id = _pick_ephemeral_target(targets, recipient_user_id)
    if target_integration_id is None:
        return {
            "mode": "unsupported",
            "error": (
                "no bound integration on this channel can deliver a private "
                "message to that recipient — ask the user conversationally instead"
            ),
        }

    session_id = current_session_id.get() or uuid.uuid4()
    message = Message(
        id=uuid.uuid4(),
        session_id=session_id,
        role="assistant",
        content=text,
        created_at=datetime.now(timezone.utc),
        actor=ActorRef.bot(bot_id),
        metadata={
            "ephemeral": True,
            "recipient_user_id": recipient_user_id,
            "source": target_integration_id,
        },
        channel_id=channel_id,
    )
    event = ChannelEvent(
        channel_id=channel_id,
        kind=ChannelEventKind.EPHEMERAL_MESSAGE,
        payload=EphemeralMessagePayload(
            message=message,
            recipient_user_id=recipient_user_id,
            target_integration_id=target_integration_id,
        ),
    )
    try:
        publish_typed(channel_id, event)
    except Exception as exc:
        logger.exception(
            "deliver_ephemeral: bus publish failed for channel=%s", channel_id,
        )
        return {"mode": "error", "error": f"publish failed: {exc}"}
    return {"mode": "ephemeral", "integration_id": target_integration_id}


def _pick_ephemeral_target(
    targets: list[tuple[str, object]],
    recipient_user_id: str,
) -> str | None:
    """Choose the binding to deliver this ephemeral to, or None.

    Strategy:
      1. Filter to bindings whose renderer has ``Capability.EPHEMERAL``.
      2. Prefer a binding that natively owns ``recipient_user_id``
         (e.g. ``U...`` for Slack). Today only Slack has EPHEMERAL, so
         step 2 is a defensive check — if/when a second integration
         ships EPHEMERAL, the per-integration native check expands
         here, not at every call site.
      3. If none native-claims the id, fall back to the first
         EPHEMERAL-capable binding.

    Returns the integration_id to target, or None if no binding can
    deliver privately.
    """
    capable: list[str] = []
    for integration_id, _target in targets:
        renderer = renderer_registry.get(integration_id)
        if renderer is None:
            continue
        if Capability.EPHEMERAL in getattr(renderer, "capabilities", frozenset()):
            capable.append(integration_id)
    if not capable:
        return None
    for integration_id in capable:
        if _claims_user_id(integration_id, recipient_user_id):
            return integration_id
    return capable[0]


def _claims_user_id(integration_id: str, recipient_user_id: str) -> bool:
    """Does ``integration_id`` natively own this user identifier?

    V1 heuristic — per-integration until we wire the full cross-integration
    identity resolver (``app.services.channels.get_user_by_integration_identity``).

    - slack: user ids start with ``U`` or ``W`` and are alphanumeric.
    - discord: user ids are numeric snowflakes.
    - bluebubbles: phone / email.
    """
    if not recipient_user_id:
        return False
    if integration_id == "slack":
        return recipient_user_id[:1] in ("U", "W") and recipient_user_id.isalnum()
    if integration_id == "discord":
        return recipient_user_id.isdigit()
    if integration_id == "bluebubbles":
        return "@" in recipient_user_id or recipient_user_id.startswith("+")
    return False
