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

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.integrations.renderer import ChannelRenderer


_registry: dict[str, "ChannelRenderer"] = {}


def register(renderer: "ChannelRenderer") -> None:
    """Register a `ChannelRenderer` under its `integration_id`.

    Raises:
        ValueError: if `integration_id` is empty, already registered,
            or `capabilities` is not a `frozenset`.
    """
    integration_id = getattr(renderer, "integration_id", None)
    if not integration_id:
        raise ValueError(
            f"renderer {type(renderer).__name__} is missing a non-empty "
            f"`integration_id` ClassVar"
        )

    capabilities = getattr(renderer, "capabilities", None)
    if not isinstance(capabilities, frozenset):
        raise ValueError(
            f"renderer {type(renderer).__name__}.capabilities must be a "
            f"frozenset[Capability], got {type(capabilities).__name__}"
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
