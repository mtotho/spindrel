"""Add group and recommended_heartbeat columns to prompt_templates.

Revision ID: 158
Revises: 157
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "158"
down_revision = "157"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prompt_templates", sa.Column("group", sa.Text(), nullable=True))
    op.add_column("prompt_templates", sa.Column("recommended_heartbeat", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("prompt_templates", "recommended_heartbeat")
    op.drop_column("prompt_templates", "group")
