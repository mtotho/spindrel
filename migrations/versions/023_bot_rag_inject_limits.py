"""Add knowledge_max_inject_chars and memory_max_inject_chars to bots table.

Revision ID: 023
Revises: 022
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("knowledge_max_inject_chars", sa.Integer(), nullable=True))
    op.add_column("bots", sa.Column("memory_max_inject_chars", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("bots", "memory_max_inject_chars")
    op.drop_column("bots", "knowledge_max_inject_chars")
