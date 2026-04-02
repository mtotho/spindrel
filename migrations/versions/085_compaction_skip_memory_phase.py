"""Add compaction_skip_memory_phase to channels.

Revision ID: 085
Revises: 084
"""
from alembic import op
import sqlalchemy as sa

revision = "085"
down_revision = "084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column(
            "compaction_skip_memory_phase",
            sa.Boolean(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("channels", "compaction_skip_memory_phase")
