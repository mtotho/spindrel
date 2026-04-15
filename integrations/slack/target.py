"""SlackTarget — typed dispatch destination for the Slack integration.

Lives in the integration package, not in ``app/domain/``, so the agent
core stays ignorant of which integrations exist. Self-registers with
``app.domain.target_registry`` at module import time. The integration
discovery loop in ``integrations/__init__.py:_load_single_integration``
auto-imports this module before ``renderer.py``, so the typed target is
available by the time the renderer registers itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from integrations.sdk import target_registry, BaseTarget as _BaseTarget


@dataclass(frozen=True)
class SlackTarget(_BaseTarget):
    """Slack channel destination.

    ``thread_ts`` is set when the message belongs in a thread reply;
    ``reply_in_thread`` controls whether outbound messages should
    inherit that thread or post at the top level.

    ``message_ts`` is the timestamp of the user's triggering message —
    hooks in ``integrations/slack/hooks.py`` read it off the dispatch
    config to attach tool-call reactions to the originating message.
    """

    type: ClassVar[Literal["slack"]] = "slack"
    integration_id: ClassVar[str] = "slack"

    channel_id: str
    token: str
    thread_ts: str | None = None
    message_ts: str | None = None
    reply_in_thread: bool = False


target_registry.register(SlackTarget)
