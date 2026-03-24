"""Make attachment message_id nullable so attachments can be created before message persistence.

Revision ID: 057
Revises: 056
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "057"
down_revision: Union[str, None] = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "attachments",
        "message_id",
        existing_type=sa.UUID(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "attachments",
        "message_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
