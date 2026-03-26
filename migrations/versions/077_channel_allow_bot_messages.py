"""Add allow_bot_messages column to channels

Revision ID: 077
Revises: 076
"""
from alembic import op
import sqlalchemy as sa

revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("channels", sa.Column("allow_bot_messages", sa.Boolean(), server_default=sa.text("false"), nullable=False))


def downgrade():
    op.drop_column("channels", "allow_bot_messages")
