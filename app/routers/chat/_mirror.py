"""Mirror messages to/from integration dispatchers."""
import logging

logger = logging.getLogger(__name__)


async def _resolve_mirror_target(channel) -> tuple[str | None, dict | None]:
    """Resolve integration type and dispatch_config for mirroring.

    Checks Channel-level fields first, then falls back to ChannelIntegration
    bindings table (used when integration was bound via the UI).
    """
    if channel.integration and channel.dispatch_config:
        logger.debug("Mirror target from channel fields: %s", channel.integration)
        return channel.integration, channel.dispatch_config

    # Fallback: check ChannelIntegration bindings
    from sqlalchemy import select
    from app.db.engine import async_session
    from app.db.models import ChannelIntegration

    try:
        async with async_session() as db:
            result = await db.execute(
                select(ChannelIntegration)
                .where(ChannelIntegration.channel_id == channel.id)
                .limit(1)
            )
            binding = result.scalar_one_or_none()
    except Exception:
        logger.warning("Failed to query ChannelIntegration for channel %s", channel.id, exc_info=True)
        return None, None

    if not binding:
        logger.debug("No ChannelIntegration binding for channel %s", channel.id)
        return None, None

    integration = binding.integration_type
    binding_config = binding.dispatch_config or {}
    logger.info(
        "Mirror: found binding type=%s client_id=%s has_dispatch_config=%s",
        integration, binding.client_id, bool(binding_config),
    )

    # Try to resolve dispatch_config via integration hook first (provides
    # credentials like server_url/password), then merge in per-binding
    # settings (text_footer, send_method) from the binding's config_fields.
    dispatch_config = None
    if binding.client_id:
        from app.agent.hooks import get_integration_meta
        meta = get_integration_meta(integration)
        if meta and meta.resolve_dispatch_config:
            dispatch_config = meta.resolve_dispatch_config(binding.client_id)
            if dispatch_config and binding_config:
                # Merge per-binding settings that the dispatcher needs
                # (e.g. send_method, text_footer for BB)
                _INTERNAL_KEYS = {"extra_wake_words", "use_bot_wake_word", "echo_suppress_window"}
                for k, v in binding_config.items():
                    if k not in _INTERNAL_KEYS and k not in dispatch_config and v not in ("", None):
                        dispatch_config[k] = v
            logger.info("Mirror: resolved dispatch_config via hook: %s", dispatch_config is not None)

    if not dispatch_config:
        if binding_config and binding_config.get("type"):
            # Binding has a full dispatch_config with type (non-config-fields style)
            dispatch_config = binding_config
        elif binding.client_id:
            # Legacy fallback: Slack-style token lookup
            prefix = f"{integration}:"
            native_id = binding.client_id.removeprefix(prefix) if binding.client_id.startswith(prefix) else None
            if native_id:
                from app.services.integration_settings import get_value
                token = get_value(integration, f"{integration.upper()}_BOT_TOKEN")
                if token:
                    dispatch_config = {"channel_id": native_id, "token": token}

    return integration, dispatch_config


async def _mirror_to_integration(
    channel, text: str, *,
    bot_id: str | None = None,
    is_user_message: bool = False,
    user=None,
    client_actions: list[dict] | None = None,
) -> None:
    """Fire-and-forget mirror to channel's integration dispatcher."""
    integration, dispatch_config = await _resolve_mirror_target(channel)
    if not integration or not dispatch_config:
        logger.debug("Mirror skipped: no integration=%s or dispatch_config=%s", integration, dispatch_config is not None)
        return
    logger.info("Mirroring %s message to %s (is_user=%s)", "user" if is_user_message else "bot", integration, is_user_message)
    from app.agent import dispatchers
    try:
        # For user messages with authenticated user: use their display name + icon
        # For anonymous user messages: fall back to [web] prefix
        user_attrs: dict = {}
        if is_user_message and user:
            from app.agent.hooks import get_user_attribution
            user_attrs = get_user_attribution(integration, user)
        elif is_user_message:
            text = f"[web] {text}"

        await dispatchers.get(integration).post_message(
            dispatch_config, text,
            bot_id=bot_id if not is_user_message else None,
            client_actions=client_actions,
            reply_in_thread=False,
            **user_attrs,
        )
    except Exception:
        logger.warning("Mirror to %s failed", integration, exc_info=True)
