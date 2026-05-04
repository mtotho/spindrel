"""Message and attachment serialization schemas.

These were originally defined inline in `app/routers/sessions.py`. They're
hoisted here so non-router code (e.g. `app/services/channel_events.py`) can
serialize Message rows for SSE delivery without importing from routers.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from pydantic import BaseModel

from app.services.tool_result_envelopes import normalize_tool_result_envelope_ids

if TYPE_CHECKING:
    from app.db.models import Attachment, Message
    from app.domain.message import Message as DomainMessage


class AttachmentBrief(BaseModel):
    id: uuid.UUID
    type: str
    filename: str
    mime_type: str
    size_bytes: int
    description: Optional[str] = None
    has_file_data: bool = False

    model_config = {"from_attributes": True}

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


def _attachments_if_loaded(msg: "Message") -> list:
    """Return msg.attachments only if the relationship is already loaded.

    Accessing a lazy relationship outside a greenlet context (i.e. from
    sync code, including pydantic serialization) raises MissingGreenlet.
    Callers serializing in fire-and-forget contexts should re-query with
    selectinload(Message.attachments) if they need attachments in the
    payload; otherwise we silently emit an empty list.
    """
    from sqlalchemy import inspect as _sa_inspect
    try:
        state = _sa_inspect(msg)
        if "attachments" in state.unloaded:
            return []
        return list(msg.attachments or [])
    except Exception:
        # Plain Python objects (e.g. SimpleNamespace in tests) won't have
        # SQLAlchemy state — fall back to direct access.
        return list(getattr(msg, "attachments", None) or [])


class FeedbackTotals(BaseModel):
    up: int = 0
    down: int = 0


class FeedbackBlock(BaseModel):
    """Per-turn feedback summary attached to the anchor message of a turn.

    The anchor is the last user-visible assistant text message in the turn
    (see ``app.services.turn_feedback.anchor_message_id_for_correlation``).
    Only the requesting user's own vote and own comment are exposed.
    """

    mine: Optional[str] = None  # "up" | "down" | None
    totals: FeedbackTotals = FeedbackTotals()
    comment_mine: Optional[str] = None


class MessageOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: Optional[str] = None
    tool_calls: Optional[list] = None
    tool_call_id: Optional[str] = None
    correlation_id: Optional[uuid.UUID] = None
    created_at: datetime
    metadata: dict = {}
    attachments: list[AttachmentBrief] = []
    feedback: Optional[FeedbackBlock] = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, msg: "Message") -> "MessageOut":
        metadata = dict(msg.metadata_ or {})
        if isinstance(metadata.get("tool_results"), list):
            metadata["tool_results"] = normalize_tool_result_envelope_ids(
                msg.tool_calls,
                metadata["tool_results"],
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
            metadata=metadata,
            attachments=[AttachmentBrief.from_orm(a) for a in _attachments_if_loaded(msg)],
        )

    @classmethod
    def from_domain(cls, msg: "DomainMessage") -> "MessageOut":
        """Construct from a domain Message (not the ORM row).

        The domain Message is what flows on the channel-events bus
        (`app.domain.message.Message`). HTTP responses still use this
        pydantic schema; this classmethod bridges the two so a bus
        consumer that wants to serve an HTTP-shaped payload can do so
        without re-fetching the ORM row.

        Attachments are mapped through AttachmentBrief manually because
        the domain type uses a frozen tuple of frozen dataclasses while
        this schema expects pydantic models.
        """
        return cls(
            id=msg.id,
            session_id=msg.session_id,
            role=msg.role,
            content=msg.content,
            tool_calls=msg.tool_calls,
            tool_call_id=msg.tool_call_id,
            correlation_id=msg.correlation_id,
            created_at=msg.created_at,
            metadata=dict(msg.metadata or {}),
            attachments=[
                AttachmentBrief(
                    id=a.id,
                    type=a.type,
                    filename=a.filename,
                    mime_type=a.mime_type,
                    size_bytes=a.size_bytes,
                    description=a.description,
                    has_file_data=a.has_file_data,
                )
                for a in msg.attachments
            ],
        )
