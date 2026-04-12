"""Renderer registry — central directory of every `ChannelRenderer`.

Concrete renderers register themselves at import time:

    from app.integrations.renderer_registry import register
    register(SlackRenderer())

The registry validates:

- `integration_id` is unique (a duplicate registration is a programmer
  error and raises `ValueError`).
- `capabilities` is a `frozenset[Capability]` (declared as ClassVar on
  the renderer class — enforced so capability sets cannot be mutated
  after registration).

This registry coexists with `app/agent/dispatchers.py:_registry`
throughout Phases B–F. The old dispatcher registry remains the live
delivery path until Phase F migrates Slack/Discord and Phase G
migrates BlueBubbles. After Phase G, `app/agent/dispatchers.py` is
deleted entirely and this registry becomes the only delivery directory.

Phase B is inert: nothing registers here yet, so `all_renderers()`
returns an empty dict and `IntegrationDispatcherTask` instances are
never started by the lifespan loop. The wiring is in place so Phase
F can register `SlackRenderer` with a single `register(...)` call.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.integrations.renderer import ChannelRenderer

logger = logging.getLogger(__name__)

_registry: dict[str, "ChannelRenderer"] = {}


def register(renderer: "ChannelRenderer") -> None:
    """Register a `ChannelRenderer` under its `integration_id`.

    If the integration's YAML manifest declares ``capabilities``, those
    override the renderer's ClassVar (YAML is the source of truth).
    A migration warning is logged when YAML and ClassVar disagree.

    Raises:
        ValueError: if `integration_id` is empty, already registered,
            or capabilities cannot be resolved from either source.
    """
    integration_id = getattr(renderer, "integration_id", None)
    if not integration_id:
        raise ValueError(
            f"renderer {type(renderer).__name__} is missing a non-empty "
            f"`integration_id` ClassVar"
        )

    # Resolve capabilities: YAML manifest wins over ClassVar
    from app.services.integration_manifests import get_capabilities
    from app.domain.capability import Capability

    yaml_caps = get_capabilities(integration_id)
    classvar_caps = getattr(renderer, "capabilities", None)

    if yaml_caps is not None:
        resolved = frozenset(Capability(c) for c in yaml_caps)

        if isinstance(classvar_caps, frozenset) and classvar_caps != resolved:
            logger.warning(
                "renderer %s: YAML capabilities differ from ClassVar "
                "(YAML=%s, ClassVar=%s) — using YAML as source of truth",
                type(renderer).__name__,
                sorted(c.value for c in resolved),
                sorted(c.value for c in classvar_caps),
            )

        type(renderer).capabilities = resolved
    elif not isinstance(classvar_caps, frozenset):
        raise ValueError(
            f"renderer {type(renderer).__name__}.capabilities must be a "
            f"frozenset[Capability] or declared in integration.yaml"
        )

    if integration_id in _registry:
        existing = type(_registry[integration_id]).__name__
        incoming = type(renderer).__name__
        raise ValueError(
            f"renderer integration_id={integration_id!r} already registered "
            f"by {existing}; refusing to overwrite with {incoming}"
        )

    _registry[integration_id] = renderer


def get(integration_id: str) -> "ChannelRenderer | None":
    """Look up a renderer by integration_id, returning None if absent."""
    return _registry.get(integration_id)


def all_renderers() -> dict[str, "ChannelRenderer"]:
    """Return a snapshot of every registered renderer.

    Returned dict is a shallow copy — callers may iterate freely without
    racing concurrent registrations during startup.
    """
    return dict(_registry)


def unregister(integration_id: str) -> None:
    """Remove a renderer from the registry. Used by tests for isolation."""
    _registry.pop(integration_id, None)


def clear() -> None:
    """Drop every registered renderer. Used by tests for isolation."""
    _registry.clear()
