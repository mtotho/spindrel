"""Add model_tiers to server_config and model_tier_overrides to channels.

Named tiers (fast, standard, capable, frontier) map to concrete model+provider
pairs. Global mapping lives in server_config; per-channel overrides in channels.

Revision ID: 133
Revises: 132
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "133"
down_revision = "132"


def upgrade() -> None:
    op.add_column(
        "server_config",
        sa.Column("model_tiers", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column(
        "channels",
        sa.Column("model_tier_overrides", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("channels", "model_tier_overrides")
    op.drop_column("server_config", "model_tiers")
