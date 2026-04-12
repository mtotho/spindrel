"""Channel service: first-class persistent container for conversations."""
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session
from app.db.models import Channel, ChannelBotMember, ChannelIntegration, ChannelMember, Session

if TYPE_CHECKING:
    from app.db.models import User

logger = logging.getLogger(__name__)

INTEGRATION_CLIENT_PREFIXES = ("slack:", "discord:", "teams:", "github:")


def _default_model() -> str:
    from app.config import settings
    return settings.DEFAULT_MODEL


def derive_channel_id(client_id: str) -> uuid.UUID:
    """Derive a stable channel UUID from a client_id.

    Uses 'channel:' prefix to avoid collision with legacy session UUIDs
    derived from bare client_id.
    """
    return uuid.uuid5(uuid.NAMESPACE_DNS, f"channel:{client_id}")


def bot_channel_filter(bot_id: str):
    """WHERE clause matching channels where bot_id is primary OR member."""
    return or_(
        Channel.bot_id == bot_id,
        Channel.id.in_(
            select(ChannelBotMember.channel_id).where(ChannelBotMember.bot_id == bot_id)
        ),
    )


def is_integration_client_id(client_id: str | None) -> bool:
    if not client_id:
        return False
    from app.agent.hooks import get_all_client_id_prefixes
    prefixes = get_all_client_id_prefixes()
    if not prefixes:
        # Fallback before integrations are loaded at startup
        prefixes = INTEGRATION_CLIENT_PREFIXES
    return any(client_id.startswith(p) for p in prefixes)


async def resolve_channel_by_client_id(
    db: AsyncSession,
    client_id: str,
) -> Channel | None:
    """Find a channel via channel_integrations binding by client_id.

    Returns the first match. For multi-channel fan-out use
    ``resolve_all_channels_by_client_id`` instead.
    """
    result = await db.execute(
        select(Channel)
        .join(ChannelIntegration, ChannelIntegration.channel_id == Channel.id)
        .where(ChannelIntegration.client_id == client_id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def resolve_all_channels_by_client_id(
    db: AsyncSession,
    client_id: str,
) -> list[tuple[Channel, ChannelIntegration]]:
    """Return all (Channel, ChannelIntegration) pairs bound to *client_id*.

    Used for multi-channel fan-out: the same GitHub repo (or other source)
    can be bound to multiple channels with different event filters.
    """
    result = await db.execute(
        select(Channel, ChannelIntegration)
        .join(ChannelIntegration, ChannelIntegration.channel_id == Channel.id)
        .where(ChannelIntegration.client_id == client_id)
    )
    return list(result.tuples().all())


def _auto_set_workspace_id(channel: Channel) -> None:
    """Set workspace_id on a newly created channel from the bot's shared workspace."""
    try:
        from app.agent.bots import get_bot
        bot = get_bot(channel.bot_id)
        channel.workspace_id = uuid.UUID(bot.shared_workspace_id)
    except Exception:
        logger.debug("Could not auto-set workspace_id for channel bot_id=%s (bot not loaded yet?)", channel.bot_id)


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
    1. channel_id provided → look up directly; if not found, create with that ID (skip client_id)
    2. client_id provided (no channel_id) → look up by client_id, or create with derived ID
    3. Neither → create new channel with random UUID
    """
    # 1. Explicit channel_id
    if channel_id is not None:
        ch = await db.get(Channel, channel_id)
        if ch is not None:
            return ch
        # channel_id was explicitly requested but doesn't exist yet — skip
        # client_id fallback and create the channel with the requested ID below.

    # 2. client_id lookup (only when no explicit channel_id was requested)
    if channel_id is None and client_id is not None:
        # Legacy: check Channel.client_id directly
        result = await db.execute(
            select(Channel).where(Channel.client_id == client_id)
        )
        ch = result.scalar_one_or_none()

        # Fall back to channel_integrations table
        if ch is None:
            ch = await resolve_channel_by_client_id(db, client_id)

        if ch is not None:
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
        _auto_set_workspace_id(ch)
        db.add(ch)
        await db.flush()

        # Auto-join creator as channel member
        if user_id:
            db.add(ChannelMember(channel_id=ch.id, user_id=user_id))
            await db.flush()

        # Also create a ChannelIntegration row for new integration channels
        if integration:
            binding = ChannelIntegration(
                channel_id=ch.id,
                integration_type=integration,
                client_id=client_id,
                dispatch_config=dispatch_config,
                activated=True,
            )
            db.add(binding)
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
    _auto_set_workspace_id(ch)
    db.add(ch)
    await db.flush()

    # Auto-join creator as channel member
    if user_id:
        db.add(ChannelMember(channel_id=ch.id, user_id=user_id))
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
    has_integration = channel.integration is not None
    if not has_integration:
        # Check channel_integrations table
        result = await db.execute(
            select(ChannelIntegration.id)
            .where(ChannelIntegration.channel_id == channel.id)
            .limit(1)
        )
        has_integration = result.scalar_one_or_none() is not None

    session = Session(
        id=session_id,
        client_id=channel.client_id or f"channel:{channel.id}",
        bot_id=channel.bot_id,
        channel_id=channel.id,
        locked=has_integration,
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
    has_integration = channel.integration is not None
    if not has_integration:
        result = await db.execute(
            select(ChannelIntegration.id)
            .where(ChannelIntegration.channel_id == channel.id)
            .limit(1)
        )
        has_integration = result.scalar_one_or_none() is not None

    session_id = uuid.uuid4()
    session = Session(
        id=session_id,
        client_id=channel.client_id or f"channel:{channel.id}",
        bot_id=channel.bot_id,
        channel_id=channel.id,
        locked=has_integration,
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


async def bind_integration(
    db: AsyncSession,
    channel_id: uuid.UUID,
    integration_type: str,
    client_id: str,
    dispatch_config: dict | None = None,
    display_name: str | None = None,
) -> ChannelIntegration:
    """Bind an integration to a channel. Raises on duplicate client_id."""
    binding = ChannelIntegration(
        channel_id=channel_id,
        integration_type=integration_type,
        client_id=client_id,
        dispatch_config=dispatch_config,
        display_name=display_name,
    )
    db.add(binding)
    await db.flush()
    return binding


async def unbind_integration(
    db: AsyncSession,
    binding_id: uuid.UUID,
) -> bool:
    """Delete an integration binding. Returns True if found and deleted."""
    binding = await db.get(ChannelIntegration, binding_id)
    if binding is None:
        return False
    await db.delete(binding)
    await db.flush()
    return True


async def adopt_integration(
    db: AsyncSession,
    binding_id: uuid.UUID,
    target_channel_id: uuid.UUID,
) -> ChannelIntegration:
    """Move a binding from its current channel to target_channel_id."""
    binding = await db.get(ChannelIntegration, binding_id)
    if binding is None:
        raise ValueError(f"Binding {binding_id} not found")
    target = await db.get(Channel, target_channel_id)
    if target is None:
        raise ValueError(f"Target channel {target_channel_id} not found")
    binding.channel_id = target_channel_id
    binding.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return binding


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


async def _ensure_orchestrator_bot_exists() -> bool:
    """Ensure the orchestrator bot exists in DB, creating it if needed.

    Returns True if the bot exists (or was just created), False on failure.
    """
    from app.db.models import Bot as BotModel

    async with async_session() as db:
        existing = (await db.execute(
            select(BotModel).where(BotModel.id == "orchestrator")
        )).scalar_one_or_none()
        if existing:
            return True

        # Try YAML seeding first (preferred — keeps system_prompt in sync with file)
        from app.agent.bots import SYSTEM_BOTS_DIR
        yaml_path = SYSTEM_BOTS_DIR / "orchestrator.yaml"
        if yaml_path.exists():
            try:
                import yaml as _yaml
                from app.agent.bots import _yaml_data_to_row_dict
                from sqlalchemy.dialects.postgresql import insert as pg_insert
                with open(yaml_path) as f:
                    data = _yaml.safe_load(f)
                if data and "id" in data:
                    row_dict = _yaml_data_to_row_dict(data)
                    stmt = pg_insert(BotModel).values(**row_dict).on_conflict_do_nothing(
                        index_elements=["id"]
                    )
                    await db.execute(stmt)
                    await db.commit()
                    logger.info("Seeded orchestrator bot from YAML: %s", yaml_path)
                    return True
            except Exception:
                logger.warning("YAML seeding failed for orchestrator, falling back to inline", exc_info=True)
                await db.rollback()

        # Inline fallback — create directly
        bot = BotModel(
            id="orchestrator",
            name="Orchestrator",
            model=_default_model(),
            system_prompt=(
                "You are the Orchestrator — the central hub for this Spindrel instance.\n\n"
                "On EVERY first message, call `get_system_status` before responding.\n"
                "If `is_fresh_install: true`, walk the user through setup (provider, first bot, "
                "integrations, first channel). Otherwise, offer management.\n\n"
                "## Guidelines\n"
                "- Be concise and direct — just use tools, don't explain them.\n"
                "- Use sensible defaults. Don't ask questions you can answer yourself.\n"
                "- Never suggest editing YAML or .env — do everything through tools.\n"
                "- When creating bots, enable workspace + workspace-files memory by default.\n"
                "- Use models available from the configured provider (check get_system_status).\n"
                "- If an LLM error occurs, use `manage_bot` to update your model."
            ),
            local_tools=["get_system_status", "manage_bot", "manage_channel",
                          "manage_integration", "web_search", "get_skill"],
            skills=[
                {"id": "integration-builder", "mode": "on_demand"},
                {"id": "project-management", "mode": "on_demand"},
            ],
            tool_retrieval=True,
            context_compaction=True,
            workspace={"enabled": True},
            memory_scheme="workspace-files",
            history_mode="file",
            delegation_config={
                "delegate_bots": ["*"],
                "cross_workspace_access": True,
            },
        )
        try:
            db.add(bot)
            await db.commit()
            logger.info("Created orchestrator bot via inline fallback")
            return True
        except Exception:
            logger.error("Failed to create orchestrator bot", exc_info=True)
            return False


async def ensure_orchestrator_channel() -> None:
    """Create the orchestrator bot (if needed) and its landing channel.

    Called from lifespan after load_bots(). Idempotent.
    """
    from app.agent.bots import _registry, load_bots

    if "orchestrator" not in _registry:
        # Bot not in registry — try to ensure it exists in DB and reload
        created = await _ensure_orchestrator_bot_exists()
        if created:
            await load_bots()

    if "orchestrator" not in _registry:
        logger.warning(
            "Orchestrator bot could not be created — skipping orchestrator channel. "
            "Available bots: %s",
            list(_registry.keys()),
        )
        return

    async with async_session() as db:
        ch = await get_or_create_channel(
            db,
            client_id="orchestrator:home",
            bot_id="orchestrator",
            name="Orchestrator",
            private=True,
        )
        # Ensure admin-only visibility (no user_id + private)
        changed = False
        if not ch.private:
            ch.private = True
            changed = True
        if not ch.protected:
            ch.protected = True
            changed = True
        # Rename legacy "Home" label
        if ch.name == "Home":
            ch.name = "Orchestrator"
            changed = True
        if changed:
            ch.updated_at = datetime.now(timezone.utc)
        await ensure_active_session(db, ch)
        # Auto-apply orchestrator carapace if not already present
        existing = ch.carapaces_extra or []
        if "orchestrator" not in existing:
            ch.carapaces_extra = existing + ["orchestrator"]
            ch.updated_at = datetime.now(timezone.utc)

        # Ensure orchestrator has an allow-all tool policy rule
        from app.db.models import ToolPolicyRule
        has_rule = (await db.execute(
            select(ToolPolicyRule).where(
                ToolPolicyRule.bot_id == "orchestrator",
                ToolPolicyRule.tool_name == "*",
                ToolPolicyRule.action == "allow",
            )
        )).scalar_one_or_none()
        if not has_rule:
            db.add(ToolPolicyRule(
                bot_id="orchestrator",
                tool_name="*",
                action="allow",
                priority=0,
                reason="Orchestrator needs full tool access for system management",
                enabled=True,
            ))
            logger.info("Created allow-all tool policy rule for orchestrator bot")

        await db.commit()
    logger.info("Orchestrator landing channel ready (orchestrator:home)")
