"""widget pin presentation snapshot

Revision ID: 241
Revises: 240
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "241"
down_revision = "240"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "widget_dashboard_pins",
        sa.Column(
            "widget_presentation_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("widget_dashboard_pins", "widget_presentation_snapshot")
