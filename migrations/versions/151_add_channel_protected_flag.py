"""Add protected flag to channels.

Revision ID: 151
Revises: 150
"""
import sqlalchemy as sa
from alembic import op

revision = "151"
down_revision = "150"


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column(
            "protected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("channels", "protected")
