"""Origin resolver registry.

Each resolver claims a ``(definition_kind, instantiation_kind)`` pair.
``service.compute_pin_metadata`` walks resolvers by ``priority`` (lowest
first), takes the first ``claim()`` that returns non-None, and calls that
resolver's ``materialize()`` to produce the live fields. Adding a new
widget kind = one new file in this directory, no edits to existing
resolvers or to ``service.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Protocol, runtime_checkable

WidgetOrigin = dict[str, Any]


@dataclass(frozen=True)
class LiveFields:
    """The three public output fields a resolver materializes.

    Any of these may be ``None`` to signal "no live data" — the service
    folds them with the pin's snapshot columns.
    """
    config_schema: dict[str, Any] | None
    widget_presentation: dict[str, Any] | None
    widget_contract: dict[str, Any] | None

    @classmethod
    def empty(cls) -> "LiveFields":
        return cls(config_schema=None, widget_presentation=None, widget_contract=None)


@runtime_checkable
class OriginResolver(Protocol):
    definition_kind: ClassVar[str]
    instantiation_kinds: ClassVar[frozenset[str]]
    priority: ClassVar[int]

    def claim(self, ident, deps) -> WidgetOrigin | None: ...
    def materialize(self, origin, ident, deps) -> LiveFields: ...
    def stamp(self, origin, ident, deps) -> str | None: ...


_REGISTRY: list[type[OriginResolver]] = []


def register_resolver(cls: type[OriginResolver]) -> type[OriginResolver]:
    """Class decorator that adds a resolver to the registry.

    Resolvers are kept ordered by ``priority``; ties broken by registration
    order (deterministic per import).
    """
    if cls not in _REGISTRY:
        _REGISTRY.append(cls)
        _REGISTRY.sort(key=lambda r: r.priority)
    return cls


def all_resolvers() -> list[OriginResolver]:
    """Return live instances of every registered resolver, ordered by priority."""
    # Trigger the resolver module imports lazily so the registry is populated
    # before first use even if ``pin_contract.resolvers`` was the only thing
    # imported at startup.
    from app.services.pin_contract.resolvers import (  # noqa: F401
        direct_tool,
        html_library,
        html_runtime,
        native,
        preset_tool,
    )
    return [cls() for cls in _REGISTRY]
