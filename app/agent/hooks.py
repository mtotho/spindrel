"""Integration hook system — metadata registry + lifecycle hooks.

Two registries following the existing dispatcher pattern (app/agent/dispatchers.py):

**Integration metadata** (keyed by integration type):
  - client_id_prefix, user_attribution, resolve_display_names

**Lifecycle hooks** (broadcast, fire-and-forget, errors swallowed):
  - after_tool_call, after_response, before_context_assembly
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

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


_meta_registry: dict[str, IntegrationMeta] = {}


def register_integration(meta: IntegrationMeta) -> None:
    """Register an integration's metadata (prefix, attribution, display names)."""
    _meta_registry[meta.integration_type] = meta
    logger.debug("Registered integration meta: %s (prefix=%s)", meta.integration_type, meta.client_id_prefix)


def get_integration_meta(integration_type: str) -> IntegrationMeta | None:
    return _meta_registry.get(integration_type)


def get_all_client_id_prefixes() -> tuple[str, ...]:
    """Return all registered client_id prefixes (e.g. ('slack:', 'discord:'))."""
    return tuple(m.client_id_prefix for m in _meta_registry.values())


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
    """Fire all registered callbacks for the given event. Errors are swallowed."""
    callbacks = _lifecycle_hooks.get(event)
    if not callbacks:
        return
    for cb in callbacks:
        try:
            ret = cb(ctx, **kwargs)
            if asyncio.iscoroutine(ret):
                await ret
        except Exception:
            logger.warning("Lifecycle hook %s error in %s", event, getattr(cb, "__qualname__", cb), exc_info=True)
