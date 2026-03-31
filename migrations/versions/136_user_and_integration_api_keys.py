"""Add users.api_key_id FK for scoped API key provisioning.

Mirrors the existing Bot.api_key_id pattern — each user gets a scoped API key
with role-appropriate permissions (admin or member preset).

Integration API keys are stored via IntegrationSetting("_api_key_id") so no
schema change is needed for integrations.

Revision ID: 136
Revises: 135
"""

import sqlalchemy as sa
from alembic import op

revision = "136"
down_revision = "135"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "api_key_id",
            sa.UUID(),
            sa.ForeignKey("api_keys.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "api_key_id")
