"""Add supports_tools flag to provider_models.

Models that don't support function calling (e.g. image generation models)
can be flagged so tools are never sent to them.

Revision ID: 138
Revises: 137
"""

import sqlalchemy as sa
from alembic import op

revision = "138"
down_revision = "137"


def upgrade() -> None:
    op.add_column(
        "provider_models",
        sa.Column(
            "supports_tools",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("provider_models", "supports_tools")
