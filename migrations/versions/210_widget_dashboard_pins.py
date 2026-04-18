"""Widget dashboard pins — a chat-less home for pinned widgets.

Phase 2 of the Widget Dashboard + Developer Panel track. Persists widgets
that live on the `/widgets` dashboard rather than inside a channel's
OmniPanel. Row shape mirrors `channel.config.pinned_widgets[]` so the
existing `PinnedToolWidget` component renders both surfaces through one
scope-aware path.

`dashboard_key` defaults to `'default'` — one global dashboard for now.
The column is reserved for multi-dashboard support later without
requiring another migration.

Revision ID: 210
Revises: 209
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "210"
down_revision = "209"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "widget_dashboard_pins",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "dashboard_key", sa.Text(), nullable=False,
            server_default=sa.text("'default'"),
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column(
            "source_channel_id", UUID(as_uuid=True),
            sa.ForeignKey("channels.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_bot_id", sa.Text(), nullable=True),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column(
            "tool_args", JSONB(), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "widget_config", JSONB(), nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("envelope", JSONB(), nullable=False),
        sa.Column("display_label", sa.Text(), nullable=True),
        sa.Column(
            "pinned_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint(
            "source_kind IN ('channel','adhoc')",
            name="ck_wdp_source_kind",
        ),
    )
    op.create_index(
        "ix_widget_dashboard_pins_key_pos",
        "widget_dashboard_pins",
        ["dashboard_key", "position"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_widget_dashboard_pins_key_pos",
        table_name="widget_dashboard_pins",
    )
    op.drop_table("widget_dashboard_pins")
