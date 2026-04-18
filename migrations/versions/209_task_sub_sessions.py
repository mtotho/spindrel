"""Task sub-sessions — Phase 0 of the pipeline-as-chat refactor.

Adds the columns that let a Task optionally run inside a dedicated Session
("sub-session") whose Messages form a rich, chat-native timeline of the run,
while the parent channel sees only a compact anchor card.

Three additions:

1. ``sessions.session_type`` (TEXT NOT NULL DEFAULT 'channel') —
   discriminates `channel` (the human-facing chat), `pipeline_run` (a
   task's run-scoped sub-session), `eval` (an evaluator case), and future
   values. Existing rows default to 'channel'. The sub-agent delegation
   path (which already uses parent_session_id/root_session_id/depth) keeps
   session_type='channel' — those aren't isolated runs.

2. ``tasks.run_isolation`` (TEXT NOT NULL DEFAULT 'inline') — per-task
   opt-in for sub-session execution. 'inline' = today's behavior (output
   flows to the parent session). 'sub_session' = spawn a dedicated Session
   at run start and route all step output there. Backfill sets
   'sub_session' on existing task_type IN ('pipeline','eval') rows so no
   pipeline regresses.

3. ``tasks.run_session_id`` (UUID nullable, FK→sessions) — for isolated
   runs, the id of the sub-session created at run start. Null otherwise.
   ON DELETE SET NULL matches the Session.source_task_id convention.

Also adds an index on (sessions.parent_session_id, sessions.session_type)
so the run-view modal's "find this task's sub-session" queries are cheap.

Revision ID: 209
Revises: 208
"""
from alembic import op
import sqlalchemy as sa


revision = "209"
down_revision = "208"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. sessions.session_type
    op.add_column(
        "sessions",
        sa.Column(
            "session_type",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'channel'"),
        ),
    )

    # 2. tasks.run_isolation
    op.add_column(
        "tasks",
        sa.Column(
            "run_isolation",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'inline'"),
        ),
    )

    # 3. tasks.run_session_id
    op.add_column(
        "tasks",
        sa.Column(
            "run_session_id",
            sa.dialects.postgresql.UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36),
            nullable=True,
        ),
    )
    # FK — skipped on sqlite (batch-only) since tests don't exercise cross-table
    # ON DELETE semantics; prod is postgres.
    if dialect == "postgresql":
        op.create_foreign_key(
            "fk_tasks_run_session_id",
            "tasks",
            "sessions",
            ["run_session_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Backfill: flip existing pipeline + eval tasks to sub_session so their
    # runs land in dedicated Sessions going forward. Historic runs are
    # untouched (they have no run_session_id; the anchor-reader falls back
    # to the legacy embedded steps[] metadata shape).
    op.execute(
        "UPDATE tasks SET run_isolation = 'sub_session' "
        "WHERE task_type IN ('pipeline', 'eval')"
    )

    # Index to speed up "find this task's sub-session" / "list children of
    # this parent session by type" lookups used by the modal.
    op.create_index(
        "ix_sessions_parent_id_session_type",
        "sessions",
        ["parent_session_id", "session_type"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    op.drop_index("ix_sessions_parent_id_session_type", table_name="sessions")

    if dialect == "postgresql":
        op.drop_constraint("fk_tasks_run_session_id", "tasks", type_="foreignkey")

    op.drop_column("tasks", "run_session_id")
    op.drop_column("tasks", "run_isolation")
    op.drop_column("sessions", "session_type")
