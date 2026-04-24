"""Integration hook system — metadata registry + lifecycle hooks.

Two registries following the existing dispatcher pattern (app/agent/dispatchers.py):

**Integration metadata** (keyed by integration type):
  - client_id_prefix, user_attribution, resolve_display_names

**Lifecycle hooks** (broadcast, fire-and-forget, errors swallowed):
  - before_context_assembly, before_llm_call, after_llm_call,
    before_tool_execution, after_tool_call, after_response

**Override-capable hooks** (short-circuit on first non-None return):
  - before_transcription
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.utils import safe_create_task

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Integration metadata registry
# ---------------------------------------------------------------------------

@dataclass
class IntegrationMeta:
    integration_type: str
    client_id_prefix: str
    user_attribution: Callable[[Any], dict] | None = None
    resolve_display_names: Callable[[list], Awaitable[dict]] | None = None
    resolve_dispatch_config: Callable[[str], dict | None] | None = None
    # --- Thread mirroring hooks (Phase 7 of Thread Sub-Sessions track) --
    # All three are optional; integrations without a threaded surface (e.g.
    # pure outbound webhook) simply leave them None and the generic layer
    # no-ops for them. Discord and future integrations implement these in
    # their own hooks.py alongside user_attribution / resolve_display_names.
    #
    # apply_thread_ref: given a freshly-resolved typed target and the
    #   integration-keyed ref dict stored on ``Session.integration_thread_refs``,
    #   return a new target (frozen dataclass) with whatever fields are
    #   needed to post into the thread (Slack: ``thread_ts`` +
    #   ``reply_in_thread=True``; Discord: ``thread_id`` override).
    apply_thread_ref: Callable[[Any, dict], Any] | None = None
    # build_thread_ref_from_message: given a persisted
    #   ``Message.metadata_`` dict, return an integration-specific ref dict
    #   suitable for stamping onto a new thread Session's
    #   ``integration_thread_refs`` column — or None if the message isn't
    #   thread-addressable on this integration. Used by
    #   ``POST /messages/{id}/thread`` to pre-mint the linkage when the
    #   parent message has the external id persisted.
    build_thread_ref_from_message: Callable[[dict], dict | None] | None = None
    # extract_thread_ref_from_dispatch: given a per-turn ``dispatch_config``
    #   (inbound integration event), return the ref dict that identifies
    #   which thread this turn belongs to, or None if it's not a thread
    #   reply. Slack returns ``{"channel": ..., "thread_ts": ...}`` when
    #   the inbound event has a ``thread_ts``; Discord returns a dict
    #   scoped to its own thread channel id.
    extract_thread_ref_from_dispatch: Callable[[dict], dict | None] | None = None
    # persist_delivery_metadata: mutate a ``Message.metadata_`` dict in
    #   place after a successful outbound delivery, stamping whatever
    #   integration-specific identifier the receiver needs (Slack: ``ts``
    #   + ``channel`` + ``thread_ts`` for thread-root lookup; Discord:
    #   message id + channel id). Caller guarantees the metadata dict is
    #   writable (deep-copied before invocation) — no need for the impl to
    #   clone. Target is the typed ``DispatchTarget``, useful for pulling
    #   the outbound channel/thread context.
    persist_delivery_metadata: Callable[[dict, str, Any], None] | None = None
    # claims_user_id: given a recipient_user_id string, return True iff
    #   this integration natively owns that identifier. Used by the
    #   ephemeral-dispatch integration picker to disambiguate when
    #   multiple integrations claim the same channel (e.g. Slack user ids
    #   start with U/W; Discord ids are numeric snowflakes; BlueBubbles
    #   ids are phone numbers or emails). Replaces the hard-coded
    #   ``if integration_id == "slack":`` branches that used to live in
    #   ``app/services/ephemeral_dispatch.py``.
    claims_user_id: Callable[[str], bool] | None = None
    # attachment_file_id_key: metadata key under which this integration
    #   stores its external file id (e.g. Slack stamps ``slack_file_id``
    #   via ``uploads.py::_store_slack_file_id``). The attachments
    #   service iterates every integration meta and matches the first
    #   populated key instead of hard-coding the Slack check inside
    #   ``app/services/attachments.py``.
    attachment_file_id_key: str | None = None


_meta_registry: dict[str, IntegrationMeta] = {}


def register_integration(meta: IntegrationMeta) -> None:
    """Register an integration's metadata (prefix, attribution, display names).

    If an auto-registered entry already exists (from manifest), merge:
    hooks.py callbacks win, manifest static fields fill gaps.
    """
    existing = _meta_registry.get(meta.integration_type)
    if existing:
        # Merge: prefer hooks.py values, fall back to auto-registered
        meta = IntegrationMeta(
            integration_type=meta.integration_type,
            client_id_prefix=meta.client_id_prefix or existing.client_id_prefix,
            user_attribution=meta.user_attribution or existing.user_attribution,
            resolve_display_names=meta.resolve_display_names or existing.resolve_display_names,
            resolve_dispatch_config=meta.resolve_dispatch_config or existing.resolve_dispatch_config,
            apply_thread_ref=meta.apply_thread_ref or existing.apply_thread_ref,
            build_thread_ref_from_message=(
                meta.build_thread_ref_from_message
                or existing.build_thread_ref_from_message
            ),
            extract_thread_ref_from_dispatch=(
                meta.extract_thread_ref_from_dispatch
                or existing.extract_thread_ref_from_dispatch
            ),
            persist_delivery_metadata=(
                meta.persist_delivery_metadata
                or existing.persist_delivery_metadata
            ),
            claims_user_id=meta.claims_user_id or existing.claims_user_id,
            attachment_file_id_key=(
                meta.attachment_file_id_key or existing.attachment_file_id_key
            ),
        )
    _meta_registry[meta.integration_type] = meta
    logger.debug("Registered integration meta: %s (prefix=%s)", meta.integration_type, meta.client_id_prefix)


def auto_register_from_manifest(integration_id: str, manifest: dict) -> None:
    """Create a minimal IntegrationMeta from manifest data.

    Called after discover_integrations() to fill gaps for integrations
    that have ``binding.client_id_prefix`` in their manifest but no
    hooks.py (or a hooks.py that doesn't call register_integration).
    No-ops if already registered.
    """
    if integration_id in _meta_registry:
        return
    binding = manifest.get("binding", {})
    prefix = binding.get("client_id_prefix", "")
    if not prefix:
        return
    _meta_registry[integration_id] = IntegrationMeta(
        integration_type=integration_id,
        client_id_prefix=prefix,
    )
    logger.debug("Auto-registered integration meta from manifest: %s (prefix=%s)", integration_id, prefix)


def get_integration_meta(integration_type: str) -> IntegrationMeta | None:
    return _meta_registry.get(integration_type)


def iter_integration_meta() -> list[IntegrationMeta]:
    """Public iterator over all registered integration metas.

    Used by anywhere that needs to fan out over every registered
    integration (e.g. thread-spawn pre-mint walking every integration's
    ``build_thread_ref_from_message`` hook). Returns a list snapshot so
    callers don't have to worry about mutation during iteration.
    """
    return list(_meta_registry.values())


def get_all_client_id_prefixes() -> tuple[str, ...]:
    """Return all registered client_id prefixes (e.g. ('slack:', 'discord:'))."""
    return tuple(m.client_id_prefix for m in _meta_registry.values())


def integration_id_from_sender_id(sender_id: str) -> str | None:
    """Resolve a ``<prefix>:<id>``-style sender to its integration id.

    Returns the ``integration_type`` whose ``client_id_prefix`` matches the
    sender's prefix, or ``None`` if no registered integration claims it.
    """
    if not sender_id:
        return None
    for meta in _meta_registry.values():
        if meta.client_id_prefix and sender_id.startswith(meta.client_id_prefix):
            return meta.integration_type
    return None


def claims_user_id(integration_id: str, recipient_user_id: str) -> bool:
    """Does ``integration_id`` natively own this user identifier?

    Looks up the integration's registered ``claims_user_id`` predicate and
    returns its result, defaulting to ``False`` if the integration has not
    registered one (or is unknown).
    """
    if not recipient_user_id:
        return False
    meta = _meta_registry.get(integration_id)
    if meta is None or meta.claims_user_id is None:
        return False
    try:
        return bool(meta.claims_user_id(recipient_user_id))
    except Exception:
        logger.warning("claims_user_id failed for %s", integration_id, exc_info=True)
        return False


def integration_id_from_attachment_meta(meta: dict) -> str | None:
    """Return the integration that stamped this attachment's metadata.

    Iterates every registered integration's ``attachment_file_id_key`` and
    returns the first one whose key is populated in ``meta``. Returns
    ``None`` if no integration claims the metadata.
    """
    if not meta:
        return None
    for im in _meta_registry.values():
        key = im.attachment_file_id_key
        if key and meta.get(key):
            return im.integration_type
    return None


def get_user_attribution(integration_type: str, user: Any) -> dict:
    """Dispatch user_attribution to the correct integration. Returns {} if unknown."""
    meta = _meta_registry.get(integration_type)
    if meta and meta.user_attribution:
        try:
            return meta.user_attribution(user)
        except Exception:
            logger.warning("user_attribution failed for %s", integration_type, exc_info=True)
    return {}


async def resolve_all_display_names(channels: list) -> dict:
    """Resolve display names across all registered integrations.

    Groups channels by integration type and dispatches to each integration's
    resolve_display_names callback. Returns {channel_id: "#name"}.
    """
    by_integration: dict[str, list] = {}
    for ch in channels:
        if ch.integration:
            by_integration.setdefault(ch.integration, []).append(ch)

    result: dict = {}
    tasks = []
    for integration_type, chs in by_integration.items():
        meta = _meta_registry.get(integration_type)
        if meta and meta.resolve_display_names:
            async def _resolve(fn=meta.resolve_display_names, channels=chs, itype=integration_type):
                try:
                    names = await fn(channels)
                    result.update(names)
                except Exception:
                    logger.warning("resolve_display_names failed for %s", itype, exc_info=True)
            tasks.append(_resolve())

    if tasks:
        await asyncio.gather(*tasks)
    return result


# ---------------------------------------------------------------------------
# Lifecycle hooks (broadcast, fire-and-forget)
# ---------------------------------------------------------------------------

@dataclass
class HookContext:
    bot_id: str | None = None
    session_id: Any = None
    channel_id: Any = None
    client_id: str | None = None
    correlation_id: Any = None
    extra: dict = field(default_factory=dict)


_lifecycle_hooks: dict[str, list[Callable]] = {}


def register_hook(event: str, callback: Callable) -> None:
    """Register a lifecycle hook callback for the given event name."""
    _lifecycle_hooks.setdefault(event, []).append(callback)
    logger.debug("Registered lifecycle hook: %s -> %s", event, callback.__qualname__)


async def fire_hook(event: str, ctx: HookContext, **kwargs) -> None:
    """Fire all registered callbacks for the given event. Errors are swallowed.

    Also emits webhook POSTs to DB-configured webhook endpoints (fire-and-forget).
    """
    callbacks = _lifecycle_hooks.get(event)
    if callbacks:
        for cb in callbacks:
            try:
                ret = cb(ctx, **kwargs)
                if asyncio.iscoroutine(ret):
                    await ret
            except Exception:
                logger.warning("Lifecycle hook %s error in %s", event, getattr(cb, "__qualname__", cb), exc_info=True)

    # Webhook emission
    _emit_webhook(event, ctx)


async def fire_hook_with_override(event: str, ctx: HookContext, **kwargs) -> Any:
    """Fire callbacks for *event*; return the first non-None result (short-circuit).

    Used for hooks where an integration can *replace* default behavior
    (e.g. ``before_transcription`` providing custom STT).

    Also emits webhook POSTs (fire-and-forget, same as ``fire_hook``).
    """
    callbacks = _lifecycle_hooks.get(event)
    if callbacks:
        for cb in callbacks:
            try:
                ret = cb(ctx, **kwargs)
                if asyncio.iscoroutine(ret):
                    ret = await ret
                if ret is not None:
                    _emit_webhook(event, ctx)
                    return ret
            except Exception:
                logger.warning("Lifecycle hook %s error in %s", event, getattr(cb, "__qualname__", cb), exc_info=True)

    _emit_webhook(event, ctx)
    return None


# ---------------------------------------------------------------------------
# Webhook emission — delegates to DB-backed webhook service
# ---------------------------------------------------------------------------

def _emit_webhook(event: str, ctx: HookContext) -> None:
    """Schedule fire-and-forget webhook delivery via the DB-backed webhook service."""
    from app.services.webhooks import emit_webhooks

    payload = {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "context": {
            "bot_id": ctx.bot_id,
            "session_id": str(ctx.session_id) if ctx.session_id else None,
            "channel_id": str(ctx.channel_id) if ctx.channel_id else None,
            "client_id": ctx.client_id,
            "correlation_id": str(ctx.correlation_id) if ctx.correlation_id else None,
        },
        "data": ctx.extra,
    }
    safe_create_task(emit_webhooks(event, payload))

    # Fire event-triggered tasks matching this system event
    from app.agent.tasks import fire_event_triggers
    safe_create_task(fire_event_triggers("system", event, ctx.extra or {}))
