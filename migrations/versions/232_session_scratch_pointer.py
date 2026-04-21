"""Add sessions.parent_channel_id, owner_user_id, is_current for cross-device scratch.

Scratch (ephemeral) sessions were pinned to a single device via a
localStorage-stored session_id. Opening the same channel's scratch on a
second device spawned a fresh session and orphaned the first.

This migration moves the "current scratch session for this (user,
channel)" pointer onto the ``sessions`` row itself:

- ``parent_channel_id`` — the channel the scratch chat belongs to (FK,
  ON DELETE SET NULL so deleting a channel detaches but keeps transcripts).
- ``owner_user_id`` — the user who owns the scratch session (FK, ON
  DELETE SET NULL). Bot id alone is ambiguous — two users sharing a
  channel each get their own scratch pointer.
- ``is_current`` — boolean flag marking the active scratch for a
  (user, channel). Reset flips this to false on the old row and true on
  the new one; the old row stays queryable in history.

Partial unique index enforces one current scratch per (user, channel,
session_type='ephemeral') at the DB layer. Postgres's partial-index
``WHERE`` clause handles the predicate. SQLite supports partial indexes
too (``sqlite_where``), but the test suite primarily exercises the
race-free path via application-level locking, so the unique constraint
is a belt-and-suspenders.

Revision ID: 232
Revises: 231
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "232"
down_revision = "231"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column(
            "parent_channel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("channels.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "owner_user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_sessions_scratch_pointer",
        "sessions",
        ["parent_channel_id", "owner_user_id", "session_type"],
        postgresql_where=sa.text("is_current"),
        sqlite_where=sa.text("is_current"),
    )
    op.create_index(
        "uq_sessions_current_scratch",
        "sessions",
        ["parent_channel_id", "owner_user_id"],
        unique=True,
        postgresql_where=sa.text("is_current AND session_type = 'ephemeral'"),
        sqlite_where=sa.text("is_current AND session_type = 'ephemeral'"),
    )


def downgrade() -> None:
    op.drop_index("uq_sessions_current_scratch", table_name="sessions")
    op.drop_index("ix_sessions_scratch_pointer", table_name="sessions")
    op.drop_column("sessions", "is_current")
    op.drop_column("sessions", "owner_user_id")
    op.drop_column("sessions", "parent_channel_id")
