"""Add provider_models table for DB-backed model lists.

Revision ID: 083
Revises: 082
"""

from alembic import op
import sqlalchemy as sa

revision = "083"
down_revision = "082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_models",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "provider_id",
            sa.Text,
            sa.ForeignKey("provider_configs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_id", sa.Text, nullable=False),
        sa.Column("display_name", sa.Text, nullable=True),
        sa.Column("max_tokens", sa.Integer, nullable=True),
        sa.Column("input_cost_per_1m", sa.Text, nullable=True),
        sa.Column("output_cost_per_1m", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("provider_id", "model_id", name="uq_provider_model"),
    )


def downgrade() -> None:
    op.drop_table("provider_models")
