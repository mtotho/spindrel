"""Domain Message — the bus-shipped representation of a message.

Distinct from `app.db.models.Message` (the SQLAlchemy ORM row) and from
`app.schemas.messages.MessageOut` (the HTTP serialization). The domain
Message is what flows on the channel-events bus and through the outbox.

The three exist because they have three different audiences:

  ORM Message       — SQLAlchemy entity, has relationships, requires a session
  Domain Message    — frozen dataclass, what the bus carries, JSON-serializable
  MessageOut        — pydantic, what HTTP returns to clients

The domain type is a frozen dataclass (not pydantic) for two reasons:
  1. It crosses the bus boundary; no need for HTTP-specific validation
  2. Frozen guarantees no in-flight mutation by renderer subscribers

Phase A introduces the type and a `from_orm` constructor. Subsequent phases
make the bus emit it instead of dict metadata.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from app.services.tool_result_envelopes import normalize_tool_result_envelope_ids

from app.domain.actor import ActorRef

if TYPE_CHECKING:
    from app.db.models import Attachment, Message as ORMMessage


@dataclass(frozen=True)
class AttachmentBrief:
    """Minimal attachment representation for the bus.

    Mirrors `app.schemas.messages.AttachmentBrief` but as a frozen
    dataclass instead of pydantic, so it's bus-safe.
    """

    id: uuid.UUID
    type: str
    filename: str
    mime_type: str
    size_bytes: int
    description: str | None = None
    has_file_data: bool = False

    @classmethod
    def from_orm(cls, att: "Attachment") -> "AttachmentBrief":
        return cls(
            id=att.id,
            type=att.type,
            filename=att.filename,
            mime_type=att.mime_type,
            size_bytes=att.size_bytes,
            description=att.description,
            has_file_data=att.file_data is not None,
        )


@dataclass(frozen=True)
class Message:
    """The bus's view of a persisted message.

    A frozen dataclass, deliberately separate from the ORM row and
    HTTP schema. Renderers consume this directly via ChannelEvents.

    `actor` is set when the message is published. For legacy messages
    that don't yet carry first-class attribution, the from_orm helper
    derives an ActorRef from `metadata` (sender_id / sender_display_name)
    and `role`. The migration to first-class attribution is gradual.
    """

    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str | None
    created_at: datetime
    actor: ActorRef
    correlation_id: uuid.UUID | None = None
    tool_calls: list | None = None
    tool_call_id: str | None = None
    metadata: dict = field(default_factory=dict)
    attachments: tuple[AttachmentBrief, ...] = ()
    channel_id: uuid.UUID | None = None

    @classmethod
    def from_orm(
        cls,
        msg: "ORMMessage",
        *,
        channel_id: uuid.UUID | None = None,
    ) -> "Message":
        """Construct from an ORM row.

        Derives the ActorRef from existing metadata fields. Legacy rows
        store sender info in `metadata_["sender_id"]` and
        `metadata_["sender_display_name"]`; we read those if present and
        fall back to a role-based default.

        Attachments are read only if already loaded on the ORM row
        (matches MessageOut.from_orm semantics — see _attachments_if_loaded
        in app/schemas/messages.py).
        """
        meta = dict(msg.metadata_ or {})
        if isinstance(meta.get("tool_results"), list):
            meta["tool_results"] = normalize_tool_result_envelope_ids(
                msg.tool_calls,
                meta["tool_results"],
            )
        actor = _derive_actor(msg.role, meta)
        attachments = tuple(
            AttachmentBrief.from_orm(a) for a in _attachments_if_loaded(msg)
        )
        return cls(
            id=msg.id,
            session_id=msg.session_id,
            role=msg.role,
            content=msg.content,
            tool_calls=msg.tool_calls,
            tool_call_id=msg.tool_call_id,
            correlation_id=msg.correlation_id,
            created_at=msg.created_at,
            metadata=meta,
            attachments=attachments,
            actor=actor,
            channel_id=channel_id,
        )

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict for outbox storage."""
        return {
            "id": str(self.id),
            "session_id": str(self.session_id),
            "channel_id": str(self.channel_id) if self.channel_id else None,
            "role": self.role,
            "content": self.content,
            "tool_calls": self.tool_calls,
            "tool_call_id": self.tool_call_id,
            "correlation_id": str(self.correlation_id) if self.correlation_id else None,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
            "attachments": [
                {
                    "id": str(a.id),
                    "type": a.type,
                    "filename": a.filename,
                    "mime_type": a.mime_type,
                    "size_bytes": a.size_bytes,
                    "description": a.description,
                    "has_file_data": a.has_file_data,
                }
                for a in self.attachments
            ],
            "actor": {
                "kind": self.actor.kind,
                "id": self.actor.id,
                "display_name": self.actor.display_name,
                "avatar": self.actor.avatar,
            },
        }


def _derive_actor(role: str, metadata: dict) -> ActorRef:
    """Best-effort ActorRef from a legacy ORM row.

    Reads `sender_id` / `sender_display_name` if present, otherwise
    falls back to a role-based default.
    """
    sender_id = metadata.get("sender_id")
    sender_display = metadata.get("sender_display_name")

    if sender_id and isinstance(sender_id, str) and sender_id.startswith("bot:"):
        return ActorRef(
            kind="bot",
            id=sender_id.removeprefix("bot:"),
            display_name=sender_display,
        )
    if sender_id and isinstance(sender_id, str) and sender_id.startswith("user:"):
        return ActorRef(
            kind="user",
            id=sender_id.removeprefix("user:"),
            display_name=sender_display,
        )

    if role == "user":
        return ActorRef(kind="user", id=sender_id or "anonymous", display_name=sender_display)
    if role == "assistant":
        return ActorRef(kind="bot", id=sender_id or "assistant", display_name=sender_display)
    if role == "tool":
        return ActorRef(kind="tool", id=sender_id or "tool", display_name=sender_display)
    return ActorRef(kind="system", id=sender_id or role, display_name=sender_display or role)


def _attachments_if_loaded(msg: "ORMMessage") -> list:
    """Return msg.attachments only if the relationship is already loaded.

    Mirrors app/schemas/messages.py._attachments_if_loaded — accessing a
    lazy relationship outside a greenlet context raises MissingGreenlet,
    so callers in fire-and-forget contexts must accept an empty list
    or selectinload(Message.attachments) before publishing.
    """
    from sqlalchemy import inspect as _sa_inspect
    try:
        state = _sa_inspect(msg)
        if "attachments" in state.unloaded:
            return []
        return list(msg.attachments or [])
    except Exception:
        return list(getattr(msg, "attachments", None) or [])
