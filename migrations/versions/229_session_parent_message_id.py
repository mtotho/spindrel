"""Add sessions.parent_message_id for message-anchored thread sub-sessions.

Reply-in-thread forks a new sub-session anchored at a specific Message.
``parent_message_id`` links the thread session back to the message it
replies to so the parent feed can render a compact thread-anchor card
beneath that message.

Nullable + ON DELETE SET NULL — deleting the parent message leaves the
thread session intact but detaches it (anchor disappears from the feed).

Revision ID: 229
Revises: 228
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "229"
down_revision = "228"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "parent_message_id",
            UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_sessions_parent_message_id",
        "sessions",
        ["parent_message_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_parent_message_id", table_name="sessions")
    op.drop_column("sessions", "parent_message_id")
