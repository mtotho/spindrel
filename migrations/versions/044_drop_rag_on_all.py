"""Drop rag_on_all from channels and integration_channel_configs.

This column was never consumed by any message handler or agent pipeline.

Revision ID: 044
Revises: 043
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "044"
down_revision: Union[str, None] = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("channels", "rag_on_all")
    op.drop_column("integration_channel_configs", "rag_on_all")


def downgrade() -> None:
    op.add_column(
        "channels",
        sa.Column("rag_on_all", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "integration_channel_configs",
        sa.Column("rag_on_all", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
