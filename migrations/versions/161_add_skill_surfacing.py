"""Add skill surfacing tracking columns.

Revision ID: 161
Revises: 160
"""

from alembic import op
import sqlalchemy as sa

revision = "161"
down_revision = "160"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("skills", sa.Column("last_surfaced_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("skills", sa.Column("surface_count", sa.Integer(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    op.drop_column("skills", "surface_count")
    op.drop_column("skills", "last_surfaced_at")
