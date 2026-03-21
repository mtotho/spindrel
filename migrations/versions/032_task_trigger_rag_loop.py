"""Add trigger_rag_loop column to tasks.

Revision ID: 032
Revises: 031
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "032"
down_revision: Union[str, None] = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("trigger_rag_loop", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("tasks", "trigger_rag_loop")
