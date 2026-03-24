"""Add model_params JSONB to bots.

Revision ID: 064
Revises: 063
Create Date: 2026-03-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bots", sa.Column("model_params", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False))


def downgrade():
    op.drop_column("bots", "model_params")
