"""Add description, category, triggers to skills table

Revision ID: 166
Revises: 165
Create Date: 2026-04-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "166"
down_revision = "165"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("skills", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("skills", sa.Column("category", sa.Text(), nullable=True))
    op.add_column(
        "skills",
        sa.Column(
            "triggers",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("skills", "triggers")
    op.drop_column("skills", "category")
    op.drop_column("skills", "description")
