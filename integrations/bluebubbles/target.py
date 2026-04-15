"""BlueBubblesTarget — typed dispatch destination for the BlueBubbles integration.

Self-registers with ``app.domain.target_registry`` at module import.
The integration discovery loop auto-imports this module before
``renderer.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from integrations.sdk import target_registry, BaseTarget as _BaseTarget


@dataclass(frozen=True)
class BlueBubblesTarget(_BaseTarget):
    """BlueBubbles iMessage chat destination.

    ``send_method`` and ``text_footer`` are per-binding overrides
    (different bindings can route through different BB send methods or
    append different signature lines).
    """

    type: ClassVar[Literal["bluebubbles"]] = "bluebubbles"
    integration_id: ClassVar[str] = "bluebubbles"

    chat_guid: str
    server_url: str
    password: str
    send_method: str | None = None
    text_footer: str | None = None
    typing_indicator: bool = True


target_registry.register(BlueBubblesTarget)
