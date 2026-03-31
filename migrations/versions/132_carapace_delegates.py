"""Add delegates JSONB column to carapaces table.

Carapaces can now declare delegate sub-agents (other carapaces or bots)
that they are authorized to invoke via delegate_to_agent.

Revision ID: 132
Revises: 131
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "132"
down_revision = "131"


def upgrade() -> None:
    op.add_column(
        "carapaces",
        sa.Column("delegates", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("carapaces", "delegates")
