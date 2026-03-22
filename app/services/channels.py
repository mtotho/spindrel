"""Channel service: first-class persistent container for conversations."""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models import Channel, Session

logger = logging.getLogger(__name__)

_INTEGRATION_PREFIXES = ("slack:", "discord:", "teams:")


def derive_channel_id(client_id: str) -> uuid.UUID:
    """Derive a stable channel UUID from a client_id.

    Uses 'channel:' prefix to avoid collision with legacy session UUIDs
    derived from bare client_id.
    """
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"channel:{client_id}")


def is_integration_client_id(client_id: str | None) -> bool:
    if not client_id:
        return False
    return any(client_id.startswith(p) for p in _INTEGRATION_PREFIXES)


async def get_or_create_channel(
    db: AsyncSession,
    *,
    client_id: str | None = None,
    bot_id: str = "default",
    channel_id: uuid.UUID | None = None,
    integration: str | None = None,
    name: str | None = None,
    dispatch_config: dict | None = None,
) -> Channel:
    """Find or create a channel. Returns the Channel row.

    Resolution order:
    1. channel_id provided → look up directly
    2. client_id provided → look up by client_id, or create with derived ID
    3. Neither → create new channel with random UUID
    """
    # 1. Explicit channel_id
    if channel_id is not None:
        ch = await db.get(Channel, channel_id)
        if ch is not None:
            # Update bot_id if changed
            if ch.bot_id != bot_id:
                ch.bot_id = bot_id
                ch.updated_at = datetime.now(timezone.utc)
                await db.flush()
            return ch

    # 2. client_id lookup
    if client_id is not None:
        result = await db.execute(
            select(Channel).where(Channel.client_id == client_id)
        )
        ch = result.scalar_one_or_none()
        if ch is not None:
            changed = False
            if ch.bot_id != bot_id:
                ch.bot_id = bot_id
                changed = True
            if dispatch_config and ch.dispatch_config != dispatch_config:
                ch.dispatch_config = dispatch_config
                changed = True
            if changed:
                ch.updated_at = datetime.now(timezone.utc)
                await db.flush()
            return ch

        # Create new channel for this client_id
        if channel_id is None:
            channel_id = derive_channel_id(client_id)
        if integration is None and is_integration_client_id(client_id):
            integration = client_id.split(":")[0]

        ch = Channel(
            id=channel_id,
            name=name or client_id,
            bot_id=bot_id,
            client_id=client_id,
            integration=integration,
            dispatch_config=dispatch_config,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(ch)
        await db.flush()
        return ch

    # 3. No client_id, no channel_id — anonymous channel
    ch = Channel(
        id=channel_id or uuid.uuid4(),
        name=name or f"chat:{bot_id}",
        bot_id=bot_id,
        integration=integration,
        dispatch_config=dispatch_config,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(ch)
    await db.flush()
    return ch


async def ensure_active_session(
    db: AsyncSession,
    channel: Channel,
) -> uuid.UUID:
    """Ensure the channel has an active session. Creates one if needed. Returns session_id."""
    if channel.active_session_id is not None:
        # Verify session still exists
        session = await db.get(Session, channel.active_session_id)
        if session is not None:
            return session.id

    # Create new session for this channel
    session_id = uuid.uuid4()
    session = Session(
        id=session_id,
        client_id=channel.client_id or f"channel:{channel.id}",
        bot_id=channel.bot_id,
        channel_id=channel.id,
        locked=channel.integration is not None,
    )
    db.add(session)

    channel.active_session_id = session_id
    channel.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return session_id


async def reset_channel_session(
    db: AsyncSession,
    channel: Channel,
) -> uuid.UUID:
    """Create a new session for the channel and set it as active.

    The old session is preserved (messages, compaction) but becomes inactive.
    Channel-scoped knowledge, tasks, and plans persist across the reset.
    """
    session_id = uuid.uuid4()
    session = Session(
        id=session_id,
        client_id=channel.client_id or f"channel:{channel.id}",
        bot_id=channel.bot_id,
        channel_id=channel.id,
        locked=channel.integration is not None,
    )
    db.add(session)

    channel.active_session_id = session_id
    channel.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.commit()
    return session_id
