"""Add requires JSONB column to carapaces table.

Stores tool/feature prerequisites for carapaces, enabling validation
that bots have all necessary tools for their configured carapaces.

Revision ID: 141
Revises: 140
"""

import sqlalchemy as sa
from alembic import op

revision = "141"
down_revision = "140"


def upgrade() -> None:
    op.add_column(
        "carapaces",
        sa.Column("requires", sa.JSON(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("carapaces", "requires")
