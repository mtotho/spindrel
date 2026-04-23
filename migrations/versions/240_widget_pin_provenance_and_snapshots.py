"""widget pin provenance and snapshots

Revision ID: 240
Revises: 239
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "240"
down_revision = "239"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "widget_dashboard_pins",
        sa.Column("widget_origin", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "widget_dashboard_pins",
        sa.Column(
            "provenance_confidence",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'inferred'"),
        ),
    )
    op.add_column(
        "widget_dashboard_pins",
        sa.Column(
            "widget_contract_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "widget_dashboard_pins",
        sa.Column(
            "config_schema_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("widget_dashboard_pins", "config_schema_snapshot")
    op.drop_column("widget_dashboard_pins", "widget_contract_snapshot")
    op.drop_column("widget_dashboard_pins", "provenance_confidence")
    op.drop_column("widget_dashboard_pins", "widget_origin")
