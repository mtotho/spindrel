"""Add transcript text column to conversation_sections.

Stores section transcripts directly in the database instead of relying
solely on filesystem files.

Revision ID: 145
Revises: 144
"""

import sqlalchemy as sa
from alembic import op

revision = "145"
down_revision = "144"


def upgrade() -> None:
    op.add_column("conversation_sections", sa.Column("transcript", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversation_sections", "transcript")
