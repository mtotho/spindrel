"""Native widget instances and pin linkage.

Adds a generic ``widget_instances`` table for first-party native app widgets
and an optional ``widget_instance_id`` foreign key on dashboard pins so
native widgets can keep persistent state separate from placement.

Revision ID: 237
Revises: 236
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "237"
down_revision = "236"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "widget_instances",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("widget_kind", sa.Text(), nullable=False),
        sa.Column("widget_ref", sa.Text(), nullable=False),
        sa.Column("scope_kind", sa.Text(), nullable=False),
        sa.Column("scope_ref", sa.Text(), nullable=False),
        sa.Column(
            "config",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "state",
            JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "widget_kind", "widget_ref", "scope_kind", "scope_ref",
            name="uq_widget_instances_kind_ref_scope",
        ),
    )
    op.create_index(
        "ix_widget_instances_ref_scope",
        "widget_instances",
        ["widget_ref", "scope_kind", "scope_ref"],
    )

    op.add_column(
        "widget_dashboard_pins",
        sa.Column("widget_instance_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_widget_dashboard_pins_widget_instance_id",
        "widget_dashboard_pins",
        "widget_instances",
        ["widget_instance_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_widget_dashboard_pins_widget_instance_id",
        "widget_dashboard_pins",
        ["widget_instance_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_widget_dashboard_pins_widget_instance_id", table_name="widget_dashboard_pins")
    op.drop_constraint(
        "fk_widget_dashboard_pins_widget_instance_id",
        "widget_dashboard_pins",
        type_="foreignkey",
    )
    op.drop_column("widget_dashboard_pins", "widget_instance_id")
    op.drop_index("ix_widget_instances_ref_scope", table_name="widget_instances")
    op.drop_table("widget_instances")
