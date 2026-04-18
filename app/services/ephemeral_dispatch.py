"""Publisher-side ephemeral dispatch with transparent fallback.

The agent's ``respond_privately`` tool calls ``deliver_ephemeral`` below.
We decide at publish time which delivery path the message should take
based on the bound renderer's capabilities:

  * Renderer declares ``EPHEMERAL`` → publish ``EPHEMERAL_MESSAGE`` on
    the bus (transient, the renderer flips it to the integration-native
    private send — chat.postEphemeral on Slack, etc.).

  * Renderer does NOT declare ``EPHEMERAL`` → persist and publish a
    regular ``NEW_MESSAGE`` (outbox-durable) with a leading visibility
    marker so the text still lands for the agent's author but broadcasts
    to the channel. The marker tells readers the bot meant this for one
    person specifically; it's a degraded experience but preserves
    delivery.

Why publisher-side and not dispatcher-side: if we rewrote on the
dispatcher we'd have to coordinate across multiple renderer tasks on the
same channel (to avoid the same message both broadcasting and going
ephemeral to the author). Deciding once, at publish time, makes the
semantics crisp.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

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

logger = logging.getLogger(__name__)


async def deliver_ephemeral(
    *,
    channel_id: uuid.UUID,
    bot_id: str,
    recipient_user_id: str,
    text: str,
) -> dict:
    """Deliver a private message to one user in the given channel.

    Returns a dict describing what happened — always contains ``mode``
    (``ephemeral`` or ``degraded_broadcast`` or ``error``). Never
    raises; errors return ``{"mode": "error", "error": "…"}`` so the
    calling agent tool can present it to the user.
    """
    if not text or not text.strip():
        return {"mode": "error", "error": "empty ephemeral message"}

    integration_id = await _resolve_integration_id(channel_id)
    if integration_id is None:
        return {"mode": "error", "error": f"channel {channel_id} not bound to an integration"}

    renderer = renderer_registry.get(integration_id)
    supports_ephemeral = bool(
        renderer and Capability.EPHEMERAL in getattr(renderer, "capabilities", frozenset())
    )

    if supports_ephemeral:
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
                "source": integration_id,
            },
            channel_id=channel_id,
        )
        event = ChannelEvent(
            channel_id=channel_id,
            kind=ChannelEventKind.EPHEMERAL_MESSAGE,
            payload=EphemeralMessagePayload(
                message=message,
                recipient_user_id=recipient_user_id,
            ),
        )
        try:
            publish_typed(channel_id, event)
        except Exception as exc:
            logger.exception(
                "deliver_ephemeral: bus publish failed for channel=%s", channel_id,
            )
            return {"mode": "error", "error": f"publish failed: {exc}"}
        return {"mode": "ephemeral", "integration_id": integration_id}

    # Degraded broadcast: renderer lacks EPHEMERAL. Fall back to a
    # regular NEW_MESSAGE with a visibility marker.
    marker = _visibility_marker(integration_id, recipient_user_id)
    broadcast_text = f"{marker}\n\n{text}".strip()
    await _enqueue_broadcast(
        channel_id=channel_id,
        bot_id=bot_id,
        text=broadcast_text,
    )
    return {"mode": "degraded_broadcast", "integration_id": integration_id}


async def _resolve_integration_id(channel_id: uuid.UUID) -> str | None:
    """Infer the channel's integration from its ``client_id`` prefix."""
    async with async_session() as db:
        row = (
            await db.execute(select(Channel).where(Channel.id == channel_id))
        ).scalar_one_or_none()
    if row is None or not row.client_id:
        return None
    prefix = row.client_id.split(":", 1)[0]
    return prefix or None


def _visibility_marker(integration_id: str, recipient_user_id: str) -> str:
    """Leading line that signals "meant for one user" on non-ephemeral channels."""
    if integration_id == "slack":
        return f":lock: _Private reply intended for_ <@{recipient_user_id}>"
    if integration_id == "discord":
        return f"🔒 _Private reply intended for_ <@{recipient_user_id}>"
    return f"🔒 Private reply intended for {recipient_user_id}"


async def _enqueue_broadcast(
    *, channel_id: uuid.UUID, bot_id: str, text: str,
) -> None:
    """Persist a bot message + publish NEW_MESSAGE for outbox + SSE."""
    from app.db.models import Message as MessageRow, Session as SessionRow
    from app.services.outbox_publish import enqueue_new_message_for_channel

    session_uuid = current_session_id.get()
    async with async_session() as db:
        if session_uuid is None:
            # Fallback: pick the latest session on the channel so the
            # message row has a valid parent even from contexts that
            # aren't inside a live turn.
            latest = (
                await db.execute(
                    select(SessionRow)
                    .where(SessionRow.channel_id == channel_id)
                    .order_by(SessionRow.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if latest is None:
                logger.warning(
                    "ephemeral_dispatch: no session for channel=%s — dropping fallback",
                    channel_id,
                )
                return
            session_uuid = latest.id

        row = MessageRow(
            session_id=session_uuid,
            role="assistant",
            content=text,
            metadata_={
                "source": "ephemeral_fallback",
                "bot_id": bot_id,
            },
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        domain_msg = Message.from_orm(row, channel_id=channel_id)

    await enqueue_new_message_for_channel(channel_id, domain_msg)
    from app.domain.payloads import MessagePayload
    publish_typed(
        channel_id,
        ChannelEvent(
            channel_id=channel_id,
            kind=ChannelEventKind.NEW_MESSAGE,
            payload=MessagePayload(message=domain_msg),
        ),
    )
