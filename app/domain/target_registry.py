"""Target registry — central directory of every ``DispatchTarget`` subclass.

Mirrors the renderer registry pattern (``app.integrations.renderer_registry``)
so that integrations can declare their own typed targets without
``app/`` having to import or hard-code them.

The boundary rule the registry enforces is the same one
``feedback_integration_boundary.md`` codifies: ``app/`` knows nothing
about which integrations exist. Each integration ships its own
``target.py`` (or co-locates it in ``renderer.py``) which calls
``register(MyTarget)`` at module import time. The integration discovery
loop in ``integrations/__init__.py:_load_single_integration``
auto-imports ``target.py`` before ``renderer.py`` so the target class
is available by the time the renderer module loads.

Core targets that aren't integration-specific (``WebTarget``,
``WebhookTarget``, ``InternalTarget``, ``NoneTarget``) are still defined
in ``app/domain/dispatch_target.py`` and pre-register themselves at
import time of that module.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.dispatch_target import _BaseTarget


_registry: dict[str, type["_BaseTarget"]] = {}


def register(target_cls: type["_BaseTarget"]) -> None:
    """Register a ``DispatchTarget`` subclass under its ``type`` discriminator.

    Raises:
        ValueError: if ``type`` is missing/empty or already registered
            (duplicate registration is a programmer error).
    """
    type_ = getattr(target_cls, "type", None)
    if not type_ or not isinstance(type_, str):
        raise ValueError(
            f"target {target_cls.__name__} is missing a non-empty `type` ClassVar"
        )
    if type_ in _registry and _registry[type_] is not target_cls:
        existing = _registry[type_].__name__
        raise ValueError(
            f"target type={type_!r} already registered by {existing}; "
            f"refusing to overwrite with {target_cls.__name__}"
        )
    _registry[type_] = target_cls


def get(type_: str) -> type["_BaseTarget"] | None:
    """Look up a target class by its ``type`` discriminator."""
    return _registry.get(type_)


def all_targets() -> dict[str, type["_BaseTarget"]]:
    """Return a snapshot of every registered target class."""
    return dict(_registry)


def unregister(type_: str) -> None:
    """Remove a target type. Used by tests for isolation."""
    _registry.pop(type_, None)


def clear() -> None:
    """Drop every registered target. Used by tests for isolation."""
    _registry.clear()
