"""Add fallback_model and fallback_model_provider_id to bots and channels.

Revision ID: 092
Revises: 091
"""
import sqlalchemy as sa
from alembic import op

revision = "092"
down_revision = "091"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("fallback_model", sa.Text(), nullable=True))
    op.add_column("bots", sa.Column(
        "fallback_model_provider_id", sa.Text(),
        sa.ForeignKey("provider_configs.id", ondelete="SET NULL"),
        nullable=True,
    ))
    op.add_column("channels", sa.Column("fallback_model", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column(
        "fallback_model_provider_id", sa.Text(),
        sa.ForeignKey("provider_configs.id", ondelete="SET NULL"),
        nullable=True,
    ))


def downgrade() -> None:
    op.drop_column("channels", "fallback_model_provider_id")
    op.drop_column("channels", "fallback_model")
    op.drop_column("bots", "fallback_model_provider_id")
    op.drop_column("bots", "fallback_model")
