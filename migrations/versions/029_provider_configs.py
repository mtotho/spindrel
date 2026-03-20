"""Add provider_configs table and model_provider_id to bots.

Revision ID: 029
Revises: 028
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "029"
down_revision: Union[str, None] = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_configs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("provider_type", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("tpm_limit", sa.Integer(), nullable=True),
        sa.Column("rpm_limit", sa.Integer(), nullable=True),
        sa.Column("config", JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.add_column("bots", sa.Column("model_provider_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_bots_model_provider_id",
        "bots", "provider_configs",
        ["model_provider_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_bots_model_provider_id", "bots", type_="foreignkey")
    op.drop_column("bots", "model_provider_id")
    op.drop_table("provider_configs")
