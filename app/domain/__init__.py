"""Domain types for the integration delivery layer.

These types are the typed vocabulary the bus, outbox, and renderer interface
all share. They replace the untyped ``dict`` payloads and
``dispatch_config: dict`` that the deleted ``app.agent.dispatchers``
Protocol used.

See vault/Projects/agent-server/Track - Integration Delivery.md for the
broader rationale and the phase-by-phase plan.

Integration-specific target classes (SlackTarget, DiscordTarget,
BlueBubblesTarget, GitHubTarget, …) live in their integration packages
(``integrations/<name>/target.py``) and self-register via
``app.domain.target_registry`` at module import. Only the abstract
``DispatchTarget`` base + the four core targets (``WebTarget``,
``WebhookTarget``, ``InternalTarget``, ``NoneTarget``) live here.
"""
from __future__ import annotations

from app.domain.actor import ActorRef
from app.domain.capability import Capability
from app.domain.channel_events import ChannelEvent, ChannelEventKind
from app.domain.delivery_state import DeliveryState
from app.domain.dispatch_target import (
    DispatchTarget,
    InternalTarget,
    NoneTarget,
    WebhookTarget,
    WebTarget,
    parse_dispatch_target,
)
# Integration-specific targets (Slack, Discord, BlueBubbles, GitHub, …)
# live in their respective ``integrations/<name>/target.py`` modules and
# self-register via ``app.domain.target_registry``. They are not
# re-exported from this package — importing them from ``app.domain``
# would re-introduce the integration boundary violation. Use
# ``parse_dispatch_target(d)`` to construct one from a dispatch_config
# dict, or import directly from the integration package when you
# genuinely need an ``isinstance`` check inside the integration.
from app.domain.message import Message
from app.domain.outbound_action import (
    AddReaction,
    DeleteMessage,
    OutboundAction,
    RequestApproval,
    UploadFile,
    UploadImage,
)
from app.domain.payloads import (
    ApprovalRequestedPayload,
    AttachmentDeletedPayload,
    ChannelEventPayload,
    DeliveryFailedPayload,
    HeartbeatTickPayload,
    MessagePayload,
    MessageUpdatedPayload,
    ReplayLapsedPayload,
    ShutdownPayload,
    ToolActivityPayload,
    TurnEndedPayload,
    TurnStartedPayload,
    TurnStreamToolStartPayload,
    TurnStreamToolResultPayload,
    TurnStreamTokenPayload,
    WorkflowProgressPayload,
)

__all__ = [
    "ActorRef",
    "Capability",
    "ChannelEvent",
    "ChannelEventKind",
    "ChannelEventPayload",
    "DeliveryState",
    "DispatchTarget",
    "WebTarget",
    "WebhookTarget",
    "InternalTarget",
    "NoneTarget",
    "parse_dispatch_target",
    "Message",
    "OutboundAction",
    "UploadImage",
    "UploadFile",
    "DeleteMessage",
    "AddReaction",
    "RequestApproval",
    "ApprovalRequestedPayload",
    "AttachmentDeletedPayload",
    "DeliveryFailedPayload",
    "HeartbeatTickPayload",
    "MessagePayload",
    "MessageUpdatedPayload",
    "ReplayLapsedPayload",
    "ShutdownPayload",
    "ToolActivityPayload",
    "TurnEndedPayload",
    "TurnStartedPayload",
    "TurnStreamTokenPayload",
    "TurnStreamToolStartPayload",
    "TurnStreamToolResultPayload",
    "WorkflowProgressPayload",
]
