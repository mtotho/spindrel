"""Add write protection columns to shared workspaces.

Revision ID: 113
Revises: 112
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "113"
down_revision = "112"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shared_workspaces",
        sa.Column("write_protected_paths", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.add_column(
        "shared_workspace_bots",
        sa.Column("write_access", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("shared_workspace_bots", "write_access")
    op.drop_column("shared_workspaces", "write_protected_paths")
