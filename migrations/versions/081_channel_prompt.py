"""Add channel_prompt column to channels table.

Revision ID: 081
Revises: 080
"""

from alembic import op
import sqlalchemy as sa

revision = "081"
down_revision = "080"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("channels", sa.Column("channel_prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("channels", "channel_prompt")
