"""DispatchTarget — typed replacement for the untyped `dispatch_config: dict`.

A DispatchTarget identifies WHERE a channel event should be delivered for a
given integration. It is the typed analogue of what `dispatch_config` carries
(Slack channel id + token + thread_ts; BlueBubbles chat guid + server url
+ password; etc.).

**Boundary rule:** integration-specific target classes MUST live in their
integration package — ``integrations/<name>/target.py`` — and register
themselves at import time via
``app.domain.target_registry.register(MyTarget)``. The integration
discovery loop in ``integrations/__init__.py:_load_single_integration``
auto-imports ``target.py`` before ``renderer.py`` so the target class
is available by the time the renderer module loads.

This file defines only:

- ``_BaseTarget``: the abstract base every target inherits.
- The four CORE targets that are not integration-specific (``WebTarget``,
  ``WebhookTarget``, ``InternalTarget``, ``NoneTarget``) and pre-register
  themselves at the bottom of this module.
- ``DispatchTarget``: a type alias for ``_BaseTarget`` so signatures
  stay typed without enumerating concrete subclasses.
- ``parse_dispatch_target(d)``: round-trips a JSONB-shaped dict back
  into the right variant by consulting the target registry.

Important constraint: ``DispatchTarget`` instances MUST NOT be mutated
after construction. Transient render-side state lives in per-channel
``RenderContext`` objects (Phase B), not on the target.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Literal

from app.domain import target_registry


@dataclass(frozen=True)
class _BaseTarget:
    """Common base for all dispatch targets. Not directly instantiable.

    Subclasses must declare a class-level ``type`` discriminator and an
    ``integration_id`` ClassVar so the renderer + target registries can
    route to them.
    """

    integration_id: ClassVar[str] = ""

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict.

        The dict always includes a ``type`` discriminator field for
        round-tripping via ``parse_dispatch_target``.
        """
        from dataclasses import asdict
        d = asdict(self)
        d["type"] = self.type  # type: ignore[attr-defined]
        return d


@dataclass(frozen=True)
class WebTarget(_BaseTarget):
    """Web UI destination — no external API. Web subscribers consume the bus directly.

    The WebTarget exists so 'web UI origin' becomes a first-class concept
    rather than 'the absence of a dispatch_config'. The WebRenderer (Phase C)
    is a no-op; its capability declaration documents what the web UI can
    actually render, but it does not need to do any work itself.
    """

    type: ClassVar[Literal["web"]] = "web"
    integration_id: ClassVar[str] = "web"


@dataclass(frozen=True)
class WebhookTarget(_BaseTarget):
    """Generic outbound HTTP webhook (POST JSON)."""

    type: ClassVar[Literal["webhook"]] = "webhook"
    integration_id: ClassVar[str] = "webhook"

    url: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class InternalTarget(_BaseTarget):
    """Cross-bot delegation destination — delivers into a parent session."""

    type: ClassVar[Literal["internal"]] = "internal"
    integration_id: ClassVar[str] = "internal"

    parent_session_id: str  # uuid as str — keep JSON-serializable


@dataclass(frozen=True)
class NoneTarget(_BaseTarget):
    """Null target — message is persisted but not delivered anywhere external."""

    type: ClassVar[Literal["none"]] = "none"
    integration_id: ClassVar[str] = "none"


# ``DispatchTarget`` is the abstract type used in signatures and
# ``isinstance`` checks. It's a type alias for ``_BaseTarget`` rather
# than a discriminated union of concrete subclasses, so adding a new
# integration target does not require editing this file.
DispatchTarget = _BaseTarget


# Pre-register the core targets. Integration-specific targets register
# themselves from their own ``target.py`` modules at import time, picked
# up by the integration discovery loop. ``app/`` knows nothing about
# them.
target_registry.register(WebTarget)
target_registry.register(WebhookTarget)
target_registry.register(InternalTarget)
target_registry.register(NoneTarget)


def parse_dispatch_target(d: dict | None) -> DispatchTarget:
    """Round-trip a serialized target dict back into the typed variant.

    Raises ValueError on unknown ``type`` or missing required fields.
    A None / empty dict resolves to ``NoneTarget()``.

    Looks up the concrete target class via ``target_registry``, so any
    integration that has imported its ``target.py`` module by the time
    this is called will be supported with zero changes here.
    """
    if not d:
        return NoneTarget()
    type_ = d.get("type")
    if not type_:
        raise ValueError("dispatch target missing required 'type' discriminator")
    cls = target_registry.get(type_)
    if cls is None:
        raise ValueError(
            f"unknown dispatch target type: {type_!r} "
            f"(no integration has registered it; check that the "
            f"integration was discovered)"
        )
    # Strip the discriminator before passing to the dataclass — ``type``
    # is a ClassVar.
    payload = {k: v for k, v in d.items() if k != "type"}

    # Integrations may need to massage the raw dispatch_config dict
    # before it can be passed to the dataclass constructor (e.g. github
    # carries a nested ``comment_target`` shape that the typed target
    # flattens). The convention: if the target class defines a
    # ``from_dispatch_config(payload: dict)`` classmethod, call it
    # instead of the default constructor. Otherwise pass the dict
    # straight in. Integrations stay self-contained — ``app/`` doesn't
    # special-case any of them.
    converter = getattr(cls, "from_dispatch_config", None)
    if callable(converter):
        try:
            return converter(payload)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid {type_} target: {exc}") from exc

    try:
        return cls(**payload)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError(f"invalid {type_} target: {exc}") from exc
