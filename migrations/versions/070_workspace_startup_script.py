"""Add startup_script to shared_workspaces

Revision ID: 070
Revises: 069
"""
from alembic import op
import sqlalchemy as sa

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "shared_workspaces",
        sa.Column("startup_script", sa.Text(), nullable=True, server_default=sa.text("'/workspace/startup.sh'")),
    )


def downgrade():
    op.drop_column("shared_workspaces", "startup_script")
