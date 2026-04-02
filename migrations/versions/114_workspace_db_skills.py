"""Add skills JSONB to shared_workspaces and skills_extra JSONB to channels.

Revision ID: 114
Revises: 113
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "114"
down_revision = "113"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shared_workspaces", sa.Column("skills", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column("channels", sa.Column("skills_extra", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("channels", "skills_extra")
    op.drop_column("shared_workspaces", "skills")
