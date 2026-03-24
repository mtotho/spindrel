"""Channel service: first-class persistent container for conversations."""
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models import Channel, Session

if TYPE_CHECKING:
    from app.db.models import User

logger = logging.getLogger(__name__)

INTEGRATION_CLIENT_PREFIXES = ("slack:", "discord:", "teams:")


def derive_channel_id(client_id: str) -> uuid.UUID:
    """Derive a stable channel UUID from a client_id.

    Uses 'channel:' prefix to avoid collision with legacy session UUIDs
    derived from bare client_id.
    """
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"channel:{client_id}")


def is_integration_client_id(client_id: str | None) -> bool:
    if not client_id:
        return False
    return any(client_id.startswith(p) for p in INTEGRATION_CLIENT_PREFIXES)


async def get_or_create_channel(
    db: AsyncSession,
    *,
    client_id: str | None = None,
    bot_id: str = "default",
    channel_id: uuid.UUID | None = None,
    integration: str | None = None,
    name: str | None = None,
    dispatch_config: dict | None = None,
    user_id: uuid.UUID | None = None,
    private: bool = False,
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
            private=private,
            user_id=user_id,
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
        private=private,
        user_id=user_id,
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

    # Create new session for this channel — flush the session row first
    # so the FK from channels.active_session_id → sessions.id is satisfied.
    session_id = uuid.uuid4()
    session = Session(
        id=session_id,
        client_id=channel.client_id or f"channel:{channel.id}",
        bot_id=channel.bot_id,
        channel_id=channel.id,
        locked=channel.integration is not None,
    )
    db.add(session)
    await db.flush()

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
    await db.flush()

    channel.active_session_id = session_id
    channel.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.commit()
    return session_id


async def switch_channel_session(
    db: AsyncSession,
    channel: Channel,
    session_id: uuid.UUID,
) -> uuid.UUID:
    """Switch a channel's active session to an existing session.

    The target session must belong to this channel.
    """
    session = await db.get(Session, session_id)
    if session is None:
        raise ValueError(f"Session {session_id} not found")
    if session.channel_id != channel.id:
        raise ValueError(f"Session {session_id} does not belong to channel {channel.id}")

    channel.active_session_id = session_id
    channel.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.commit()
    return session_id


def apply_channel_visibility(stmt, user):
    """Apply visibility filter to a channel query based on the authenticated user.

    - Admin users (or API key auth — user is a string) see all channels.
    - Regular users see: public channels + their own private channels.
    """
    from app.db.models import User
    if user is None or not isinstance(user, User):
        # API key auth or no user — see everything
        return stmt
    if user.is_admin:
        return stmt
    return stmt.where(
        or_(
            Channel.private == False,  # noqa: E712
            Channel.user_id == user.id,
        )
    )


async def resolve_integration_user(
    db: AsyncSession,
    integration: str,
    integration_user_id: str,
) -> "User | None":
    """Look up a system User by their integration identity.

    Searches User.integration_config->'{integration}'->>'user_id' for a match.
    Returns the User or None.
    """
    from app.db.models import User
    stmt = select(User).where(
        User.integration_config[integration]["user_id"].astext == integration_user_id,
        User.is_active == True,  # noqa: E712
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
