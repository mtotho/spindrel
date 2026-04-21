"""Upgrade Slack thread-ref lookup index to a partial UNIQUE index.

Migration 230 created ``ix_sessions_slack_thread_lookup`` as a non-unique
partial index for inbound Slack thread-reply routing. Concurrent inbound
events for the same ``(channel, thread_ts)`` can both miss the app-level
lookup in
``app/services/sub_sessions.py::resolve_or_spawn_external_thread_session``
and both spawn a fresh ``Session`` row, permanently splitting one
external Slack thread across multiple Spindrel thread sessions.

Replacing the index with a partial UNIQUE index pushes the race resolution
down to the database: a losing inserter hits ``IntegrityError`` and the
app-level handler in ``resolve_or_spawn_external_thread_session`` rolls
back the savepoint and re-reads the winner. SQLite does not enforce the
``WHERE`` clause at index creation time, but the test suite exercises
the conflict-handling branch via an explicit winner-row injection.

Scoped to Slack for now. When Discord / future-integration thread
mirroring lands, it adds its own sibling partial UNIQUE index per its
ref shape as part of that integration's own migration.

Revision ID: 231
Revises: 230
"""
from __future__ import annotations

from alembic import op


revision = "231"
down_revision = "230"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_sessions_slack_thread_lookup")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_sessions_slack_thread_ref
        ON sessions (
            (integration_thread_refs->'slack'->>'channel'),
            (integration_thread_refs->'slack'->>'thread_ts')
        )
        WHERE session_type = 'thread'
          AND integration_thread_refs->'slack'->>'thread_ts' IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_sessions_slack_thread_ref")
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
