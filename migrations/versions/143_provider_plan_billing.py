"""Add billing_type, plan_cost, plan_period to provider_configs.

Supports fixed-cost plan billing for providers that charge a flat
monthly/weekly rate rather than per-token pricing.

Revision ID: 143
Revises: 142
"""

import sqlalchemy as sa
from alembic import op

revision = "143"
down_revision = "142"


def upgrade() -> None:
    op.add_column(
        "provider_configs",
        sa.Column("billing_type", sa.Text(), nullable=False, server_default=sa.text("'usage'")),
    )
    op.add_column(
        "provider_configs",
        sa.Column("plan_cost", sa.Float(), nullable=True),
    )
    op.add_column(
        "provider_configs",
        sa.Column("plan_period", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("provider_configs", "plan_period")
    op.drop_column("provider_configs", "plan_cost")
    op.drop_column("provider_configs", "billing_type")
