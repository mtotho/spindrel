"""Add editor_port and editor_enabled to shared_workspaces.

Revision ID: 111
Revises: 110
"""
from alembic import op
import sqlalchemy as sa

revision = "111"
down_revision = "110"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shared_workspaces", sa.Column("editor_port", sa.Integer(), nullable=True))
    op.add_column("shared_workspaces", sa.Column("editor_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("shared_workspaces", "editor_enabled")
    op.drop_column("shared_workspaces", "editor_port")
