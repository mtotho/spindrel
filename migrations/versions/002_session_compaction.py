"""Add title, summary, summary_message_id to sessions

Revision ID: 002
Revises: 001
Create Date: 2026-03-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("summary_message_id", sa.UUID(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "summary_message_id")
    op.drop_column("sessions", "summary")
    op.drop_column("sessions", "title")
