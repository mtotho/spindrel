"""Add base_prompt boolean to bots table.

Revision ID: 068
Revises: 067
"""
from alembic import op
import sqlalchemy as sa

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "bots",
        sa.Column("base_prompt", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )


def downgrade():
    op.drop_column("bots", "base_prompt")
