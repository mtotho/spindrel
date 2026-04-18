"""Tool call status lifecycle + ToolApproval link.

Phase 2 of the chat-state-rehydration track. Three structural changes that
let the chat UI rehydrate in-flight turns from the DB on mount instead of
relying solely on the in-memory SSE stream:

1. ``tool_calls.status`` (TEXT NOT NULL DEFAULT 'running') — every dispatch
   now writes the row up-front in 'running' state and updates it on
   completion. Approval-gated calls land in 'awaiting_approval' until the
   user decides. Terminal states are 'done', 'error', 'denied', 'expired'.
2. ``tool_calls.completed_at`` (TIMESTAMP nullable) — wall-clock end time;
   created_at semantically becomes "started_at" without a rename.
3. ``tool_approvals.tool_call_id`` (UUID nullable, FK) — links an approval
   to its in-flight ``tool_calls`` row so the decide endpoint can flip the
   status without a fragile (correlation_id, tool_name, status) lookup.
4. ``tool_approvals.approval_metadata`` (JSONB nullable) — opt-in payload
   captured at approval-create time. Today carries ``_capability`` so
   orphan capability cards rendered on refresh show the friendly label
   instead of the raw ``activate_capability`` tool name. Kept separate
   from ``dispatch_metadata`` (which is route-config) for clarity.

Backfill: every existing ``tool_calls`` row completed historically, so
``status='done'`` and ``completed_at = created_at`` is the right snapshot.

Revision ID: 207
Revises: 206
"""
from alembic import op
import sqlalchemy as sa


revision = "207"
down_revision = "206"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # --- tool_calls.status / completed_at -----------------------------------
    if dialect == "postgresql":
        op.add_column(
            "tool_calls",
            sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'running'")),
        )
        op.add_column(
            "tool_calls",
            sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        )
        # Backfill historical rows: they all completed.
        bind.execute(sa.text(
            "UPDATE tool_calls SET status = 'done', completed_at = created_at "
            "WHERE completed_at IS NULL"
        ))
        op.create_index(
            "ix_tool_calls_bot_id_status", "tool_calls", ["bot_id", "status"]
        )
    else:
        # SQLite (tests): no SERVER DEFAULT for ALTER, so we add nullable + backfill.
        with op.batch_alter_table("tool_calls") as batch:
            batch.add_column(sa.Column("status", sa.Text(), nullable=True))
            batch.add_column(sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True))
        bind.execute(sa.text(
            "UPDATE tool_calls SET status = 'done', completed_at = created_at"
        ))
        op.create_index(
            "ix_tool_calls_bot_id_status", "tool_calls", ["bot_id", "status"]
        )

    # --- tool_approvals.tool_call_id / approval_metadata --------------------
    if dialect == "postgresql":
        op.add_column(
            "tool_approvals",
            sa.Column("tool_call_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_tool_approvals_tool_call_id",
            "tool_approvals", "tool_calls",
            ["tool_call_id"], ["id"],
            ondelete="SET NULL",
        )
        op.add_column(
            "tool_approvals",
            sa.Column("approval_metadata", sa.dialects.postgresql.JSONB, nullable=True),
        )
    else:
        # SQLite: skip FK (not enforced); JSONB → JSON.
        with op.batch_alter_table("tool_approvals") as batch:
            batch.add_column(sa.Column("tool_call_id", sa.String(length=36), nullable=True))
            batch.add_column(sa.Column("approval_metadata", sa.JSON, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.drop_constraint("fk_tool_approvals_tool_call_id", "tool_approvals", type_="foreignkey")
        op.drop_column("tool_approvals", "approval_metadata")
        op.drop_column("tool_approvals", "tool_call_id")
        op.drop_index("ix_tool_calls_bot_id_status", table_name="tool_calls")
        op.drop_column("tool_calls", "completed_at")
        op.drop_column("tool_calls", "status")
    else:
        with op.batch_alter_table("tool_approvals") as batch:
            batch.drop_column("approval_metadata")
            batch.drop_column("tool_call_id")
        op.drop_index("ix_tool_calls_bot_id_status", table_name="tool_calls")
        with op.batch_alter_table("tool_calls") as batch:
            batch.drop_column("completed_at")
            batch.drop_column("status")
