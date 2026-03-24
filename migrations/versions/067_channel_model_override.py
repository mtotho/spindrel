"""Add model_override and model_provider_id_override to channels.

Revision ID: 067
Revises: 066
"""
from alembic import op
import sqlalchemy as sa

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("channels", sa.Column("model_override", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("model_provider_id_override", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("channels", "model_provider_id_override")
    op.drop_column("channels", "model_override")
