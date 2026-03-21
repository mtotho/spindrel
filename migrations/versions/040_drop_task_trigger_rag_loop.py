"""Drop trigger_rag_loop column from tasks.

This feature is now stored in callback_config["trigger_rag_loop"].

Revision ID: 040
Revises: 039
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "040"
down_revision: Union[str, None] = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("tasks", "trigger_rag_loop")


def downgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("trigger_rag_loop", sa.Boolean(), nullable=False, server_default="false"),
    )
