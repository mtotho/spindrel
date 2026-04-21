"""Dispatch resolution — channel → typed DispatchTarget(s).

Phase D of the Integration Delivery refactor. The single canonical place
that converts a ``Channel`` row's legacy ``dispatch_config`` (or its
``ChannelIntegration`` bindings) into typed ``DispatchTarget`` instances.

This is the typed replacement for ``app/routers/chat/_mirror.py:_resolve_mirror_target``,
which is still on the legacy code path under flag-OFF and will be deleted
together with the rest of ``_mirror.py`` in Phase E (POST /chat → 202
lifecycle change). Until then, both resolvers coexist; this module is the
*only* one used by the outbox + drainer + IntegrationDispatcherTask path.

Differences from the legacy resolver:

- **Multi-target.** ``ChannelIntegration`` allows multiple bindings per
  channel; the legacy resolver returned the first one (``.limit(1)``)
  because mirror semantics are 1:1. The outbox path supports fanout, so
  this resolver returns *all* bindings for a channel.
- **Typed.** Returns ``list[(integration_id, DispatchTarget)]`` instead of
  ``(integration_str, dispatch_config_dict)``. The drainer routes via the
  integration_id and serializes the typed target into the outbox row.
- **Resolve-or-skip.** Any ``ChannelIntegration`` binding whose client_id
  resolves to a valid dispatch target is included; unresolvable rows
  (``mc-activated:`` stubs, missing credentials) are filtered by
  ``_resolve_binding`` returning None.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import Channel, ChannelIntegration
from app.domain.dispatch_target import (
    DispatchTarget,
    NoneTarget,
    parse_dispatch_target,
)

logger = logging.getLogger(__name__)


# Keys that live in ``ChannelIntegration.dispatch_config`` for activation /
# wake-word config but are NOT part of the dispatch credential set. Mirrors
# the same constant in ``_mirror._resolve_mirror_target``.
_INTERNAL_KEYS = {
    "extra_wake_words", "use_bot_wake_word", "echo_suppress_window",
    # Per-turn ephemeral fields — must NOT be read from the persisted binding.
    # thread_ts and message_ts are set per-message by the Slack event handler;
    # persisting them on the binding would lock all future replies into a stale
    # thread. reply_in_thread is derived from thread_ts at call time.
    "thread_ts", "message_ts", "reply_in_thread",
    # Token is resolved dynamically by _resolve_dispatch_config; stale copies
    # in binding_config should not override a rotated token.
    "token",
}


async def resolve_targets(channel: Channel) -> list[tuple[str, DispatchTarget]]:
    """Resolve every dispatch target bound to a channel.

    Returns a list of ``(integration_id, DispatchTarget)`` pairs. An empty
    binding set yields ``[("none", NoneTarget())]`` so the outbox row still
    has a deterministic terminal state and the ``NoneRenderer`` short-
    circuits cleanly.

    Resolution chain (mirrors the legacy ``_resolve_mirror_target``):

    1. ``Channel.integration`` + ``Channel.dispatch_config`` direct fields,
       if both are set.
    2. ``ChannelIntegration`` rows for the channel — for each activated
       binding, resolve the dispatch_config via the integration meta hook,
       then merge in non-internal binding-config keys, then fall back to
       the legacy ``{integration}_BOT_TOKEN`` lookup for Slack-style
       bindings if nothing else worked.
    3. Empty list → ``[("none", NoneTarget())]``.
    """
    targets: list[tuple[str, DispatchTarget]] = []

    # Step 1 — direct channel-level dispatch_config (Slack-bot pattern, etc.).
    if channel.integration and channel.dispatch_config:
        try:
            cfg = {**channel.dispatch_config, "type": channel.integration}
            target = parse_dispatch_target(cfg)
            targets.append((channel.integration, target))
            logger.debug(
                "resolve_targets[%s]: channel-level target type=%s",
                channel.id, channel.integration,
            )
        except ValueError:
            logger.warning(
                "resolve_targets[%s]: failed to parse channel-level dispatch_config (type=%s)",
                channel.id, channel.integration, exc_info=True,
            )

    # Step 2 — ChannelIntegration bindings (UI-managed).
    try:
        async with async_session() as db:
            result = await db.execute(
                select(ChannelIntegration).where(
                    ChannelIntegration.channel_id == channel.id
                )
            )
            bindings = list(result.scalars().all())
    except Exception:
        logger.warning(
            "resolve_targets[%s]: failed to query ChannelIntegration",
            channel.id, exc_info=True,
        )
        bindings = []

    for binding in bindings:
        # Skip if we already have a channel-level target for the same
        # integration type — channel-level fields win.
        if any(integ_id == binding.integration_type for integ_id, _ in targets):
            continue
        target = await _resolve_binding(binding)
        if target is None:
            continue
        targets.append((binding.integration_type, target))

    if not targets:
        return [("none", NoneTarget())]
    return targets


async def _resolve_binding(binding: ChannelIntegration) -> DispatchTarget | None:
    """Resolve a single ``ChannelIntegration`` row into a typed target.

    Mirrors the resolution chain in ``_mirror._resolve_mirror_target``:
    integration meta hook first, then merge of non-internal binding-config
    keys, then legacy Slack-style ``{INTEGRATION}_BOT_TOKEN`` fallback.
    """
    integration = binding.integration_type
    binding_config = binding.dispatch_config or {}

    dispatch_config: dict | None = None
    if binding.client_id:
        from app.agent.hooks import get_integration_meta
        meta = get_integration_meta(integration)
        if meta and meta.resolve_dispatch_config:
            dispatch_config = meta.resolve_dispatch_config(binding.client_id)
            if dispatch_config and binding_config:
                for k, v in binding_config.items():
                    if (
                        k not in _INTERNAL_KEYS
                        and k not in dispatch_config
                        and v not in ("", None)
                    ):
                        dispatch_config[k] = v

    if not dispatch_config:
        if binding_config and binding_config.get("type"):
            dispatch_config = binding_config
        elif binding.client_id:
            # Legacy Slack token fallback.
            prefix = f"{integration}:"
            native_id = (
                binding.client_id.removeprefix(prefix)
                if binding.client_id.startswith(prefix)
                else None
            )
            if native_id:
                from app.services.integration_settings import get_value
                token = get_value(integration, f"{integration.upper()}_BOT_TOKEN")
                if token:
                    dispatch_config = {"channel_id": native_id, "token": token}

    if not dispatch_config:
        logger.debug(
            "resolve_targets: no dispatch_config for binding %s (integration=%s, client_id=%s)",
            binding.id, integration, binding.client_id,
        )
        return None

    payload = {**dispatch_config}
    payload.setdefault("type", integration)
    try:
        return parse_dispatch_target(payload)
    except ValueError:
        logger.warning(
            "resolve_targets: failed to parse target for binding %s (integration=%s)",
            binding.id, integration, exc_info=True,
        )
        return None


def apply_session_thread_refs(
    session,
    targets: list[tuple[str, DispatchTarget]],
) -> list[tuple[str, DispatchTarget]]:
    """Rewrite targets so outbound posts land in an integration thread.

    For each ``(integration_id, target)`` pair, if the session carries a
    ref under that integration key, dispatch to the integration's
    ``apply_thread_ref`` hook (registered in ``IntegrationMeta``) to
    produce a target override — e.g. a SlackTarget with ``thread_ts`` +
    ``reply_in_thread=True`` set. Integrations without the hook are left
    unchanged.

    Generic — no Slack-specific branches here. Discord, etc. plug in via
    their own ``IntegrationMeta.apply_thread_ref`` callback.
    """
    refs = getattr(session, "integration_thread_refs", None) or {}
    if not refs:
        return targets

    from app.agent.hooks import get_integration_meta

    rewritten: list[tuple[str, DispatchTarget]] = []
    for integ_id, target in targets:
        ref = refs.get(integ_id)
        if ref:
            meta = get_integration_meta(integ_id)
            if meta and meta.apply_thread_ref:
                try:
                    target = meta.apply_thread_ref(target, ref)
                except Exception:
                    logger.warning(
                        "apply_thread_ref failed for %s; using unmodified target",
                        integ_id, exc_info=True,
                    )
        rewritten.append((integ_id, target))
    return rewritten


async def resolve_targets_for_session(
    session,
    parent_channel: "Channel | None",
) -> list[tuple[str, DispatchTarget]]:
    """Resolve the dispatch targets a session should post into.

    Thread sub-sessions share their parent channel's integration bindings
    but override each target's thread attribute via
    ``integration_thread_refs``. Channel sessions pass through
    ``resolve_targets(channel)`` unchanged.

    Caller supplies ``parent_channel`` (already loaded — typically the
    result of walking ``session.parent_session_id`` → channel, or the
    session's own ``channel_id`` when it's a channel session). Returns an
    empty NoneTarget list when there's no parent channel (pure
    channel-less ephemeral).
    """
    if parent_channel is None:
        return [("none", NoneTarget())]
    base = await resolve_targets(parent_channel)
    return apply_session_thread_refs(session, base)


async def resolve_target_for_renderer(
    channel_id, renderer_integration_id: str
) -> DispatchTarget | None:
    """Helper for ``IntegrationDispatcherTask`` per-renderer subscribers.

    Loads the channel, runs ``resolve_targets``, and returns the first
    target whose integration_id matches the requesting renderer (or None).
    Used by ``app/main.py`` lifespan to replace the C1 ``_no_target``
    placeholder.
    """
    async with async_session() as db:
        channel = await db.get(Channel, channel_id)
        if not channel:
            return None
        targets = await resolve_targets(channel)
    for integration_id, target in targets:
        if integration_id == renderer_integration_id:
            return target
    return None
