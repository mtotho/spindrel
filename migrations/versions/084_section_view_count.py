"""Add view_count and last_viewed_at to conversation_sections.

Revision ID: 084
Revises: 083
"""

from alembic import op
import sqlalchemy as sa

revision = "084"
down_revision = "083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation_sections", sa.Column("view_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("conversation_sections", sa.Column("last_viewed_at", sa.TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("conversation_sections", "last_viewed_at")
    op.drop_column("conversation_sections", "view_count")
