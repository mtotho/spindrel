"""tool call presentation contract

Revision ID: 238_tool_call_presentation_contract
Revises: 237
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "238_tool_call_presentation_contract"
down_revision = "237"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tool_calls", sa.Column("surface", sa.Text(), nullable=True))
    op.add_column("tool_calls", sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("tool_calls", "summary")
    op.drop_column("tool_calls", "surface")
