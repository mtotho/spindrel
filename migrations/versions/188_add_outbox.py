"""Add outbox table for durable channel-event delivery.

Phase D of the Integration Delivery Layer Refactor (see
``project-notes/Track - Integration Delivery.md``).

The outbox is the durability layer for the channel-events bus. Today,
``persist_turn`` calls ``publish_message`` after committing the message rows
(``app/services/sessions.py:540-564``); the publish is fire-and-forget on an
in-memory queue. A crash between the commit and the renderer ack silently
loses the delivery. The outbox closes that gap by recording one row per
``(channel, event, integration target)`` tuple inside the same transaction
as the message inserts. A background drainer (``app/services/outbox_drainer.py``)
picks up rows, routes them through ``renderer_registry``, and updates the
row state when the renderer returns.

Schema notes:

- ``id`` (uuid) is the only uniqueness key. The source plan called for
  ``UNIQUE(channel_id, seq, target_integration_id)``, but ``seq`` is
  assigned by the in-memory bus's monotonic counter at ``publish_typed``
  time (``app/services/channel_events.py:264``) which is *after* the
  pre-commit outbox enqueue and resets across restarts. Per-row-id
  uniqueness is sufficient: the drainer's ``mark_in_flight`` /
  ``mark_delivered`` state transitions provide the at-most-once
  guarantee, and persist_turn is called once per turn so duplicate
  enqueues never happen at the call site.
- The partial index ``ix_outbox_pending`` keeps the drainer's
  ``SELECT ... FOR UPDATE SKIP LOCKED`` cheap by skipping
  ``delivered`` / ``failed_permanent`` / ``dead_letter`` rows.
- ``payload`` and ``target`` are JSONB so the drainer can reconstitute the
  typed event and DispatchTarget after a process restart.

Revision ID: 188
Revises: 187
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "188"
down_revision: Union[str, None] = "187"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "channel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.BigInteger(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("target_integration_id", sa.Text(), nullable=False),
        sa.Column(
            "target",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "delivery_state",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        # Number of times a row has been deferred via ``defer_no_renderer``
        # (i.e. no renderer was registered for the target at drain time).
        # Tracked separately from ``attempts`` because a missing renderer is
        # a configuration state, not a delivery failure. After
        # ``DEFER_DEAD_LETTER_AFTER`` defers (~4h at 30s each) the row
        # transitions to dead_letter to prevent infinite re-queue.
        sa.Column(
            "defer_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "available_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("delivered_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("dead_letter_reason", sa.Text(), nullable=True),
    )
    # Partial index used by the drainer's fetch_pending() — keeps the
    # SELECT ... FOR UPDATE SKIP LOCKED cheap by skipping terminal rows.
    op.create_index(
        "ix_outbox_pending",
        "outbox",
        ["available_at"],
        postgresql_where=sa.text(
            "delivery_state IN ('pending','failed_retryable')"
        ),
    )
    # Lookup index for crash-recovery / observability scans by channel.
    op.create_index(
        "ix_outbox_channel_state",
        "outbox",
        ["channel_id", "delivery_state"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_channel_state", "outbox")
    op.drop_index("ix_outbox_pending", "outbox")
    op.drop_table("outbox")
