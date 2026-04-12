"""WyomingTarget -- typed dispatch destination for the Wyoming integration.

Self-registers with ``app.domain.target_registry`` at import time.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from app.domain import target_registry
from app.domain.dispatch_target import _BaseTarget


@dataclass(frozen=True)
class WyomingTarget(_BaseTarget):
    """Wyoming voice device destination.

    ``device_id`` identifies the satellite (e.g. "living-room-pi").
    ``connection_id`` is an ephemeral id for the active TCP connection,
    used by the pipeline to route audio back to the right socket.
    """

    type: ClassVar[Literal["wyoming"]] = "wyoming"
    integration_id: ClassVar[str] = "wyoming"

    device_id: str
    connection_id: str | None = None


target_registry.register(WyomingTarget)
