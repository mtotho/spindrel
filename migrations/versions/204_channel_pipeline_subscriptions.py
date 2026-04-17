"""Add channel_pipeline_subscriptions table.

Decouples pipeline *definitions* (Task rows) from *where they run*. A
subscription says "channel X can run pipeline Y, optionally on a schedule,
optionally featured in its launchpad". Replaces the implicit behavior
where every source=system task was globally visible in every channel's
launchpad.

Also seeds every existing source=system task as subscribed to the
orchestrator:home channel so the orchestrator's launchpad behavior
is unchanged after the migration.

Revision ID: 204
Revises: 203
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "204"
down_revision = "203"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_pipeline_subscriptions",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "channel_id", UUID(as_uuid=True),
            sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "task_id", UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("featured_override", sa.Boolean(), nullable=True),
        sa.Column("schedule", sa.Text(), nullable=True),
        sa.Column("schedule_config", JSONB(), nullable=True),
        sa.Column(
            "last_fired_at", sa.TIMESTAMP(timezone=True), nullable=True,
        ),
        sa.Column(
            "next_fire_at", sa.TIMESTAMP(timezone=True), nullable=True,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.UniqueConstraint(
            "channel_id", "task_id", name="uq_channel_pipeline_subscription",
        ),
    )
    op.create_index(
        "ix_channel_pipeline_subscriptions_channel",
        "channel_pipeline_subscriptions", ["channel_id"],
    )
    op.create_index(
        "ix_channel_pipeline_subscriptions_due",
        "channel_pipeline_subscriptions",
        ["next_fire_at"],
        postgresql_where=sa.text("enabled AND schedule IS NOT NULL"),
    )

    # Seed: every existing source=system pipeline is auto-subscribed to the
    # orchestrator:home channel so we don't regress its launchpad. Guarded
    # on ON CONFLICT DO NOTHING + NOT EXISTS so re-runs are idempotent and
    # the migration is safe on fresh databases without an orchestrator row.
    op.execute(
        """
        INSERT INTO channel_pipeline_subscriptions
            (channel_id, task_id, enabled, featured_override)
        SELECT c.id, t.id, true, NULL
          FROM channels c
          JOIN tasks t ON t.source = 'system'
         WHERE c.client_id = 'orchestrator:home'
         ON CONFLICT (channel_id, task_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_channel_pipeline_subscriptions_due",
        table_name="channel_pipeline_subscriptions",
    )
    op.drop_index(
        "ix_channel_pipeline_subscriptions_channel",
        table_name="channel_pipeline_subscriptions",
    )
    op.drop_table("channel_pipeline_subscriptions")
