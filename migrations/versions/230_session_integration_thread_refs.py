"""Add sessions.integration_thread_refs for per-integration thread linkage.

A thread sub-session can be mirrored to an external integration's native
thread primitive (Slack ``thread_ts``, Discord thread channel id, etc.).
This column stores the integration-keyed ref dict so the outbound
dispatch layer can route posts into the right thread and the inbound
handler can look up which Spindrel session a reply belongs to.

Nullable — vast majority of sessions (channel, ephemeral, pipeline runs,
pre-Phase-7 threads) have no integration thread linkage. The partial
index on the Slack thread lookup keys accelerates inbound routing without
ballooning index size on the unrelated sessions.

Revision ID: 230
Revises: 229
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "230"
down_revision = "229"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("integration_thread_refs", JSONB, nullable=True),
    )
    # Inbound Slack thread reply → session_id lookup. Partial index: only
    # rows with a populated ref participate.
    op.execute(
        """
        CREATE INDEX ix_sessions_slack_thread_lookup
        ON sessions (
            (integration_thread_refs->'slack'->>'channel'),
            (integration_thread_refs->'slack'->>'thread_ts')
        )
        WHERE integration_thread_refs IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sessions_slack_thread_lookup")
    op.drop_column("sessions", "integration_thread_refs")
