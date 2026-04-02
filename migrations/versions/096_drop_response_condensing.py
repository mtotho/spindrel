"""Drop response condensing columns from channels and messages.

Revision ID: 096
Revises: 095
"""
from alembic import op
import sqlalchemy as sa

revision = "096"
down_revision = "095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("channels", "response_condensing_enabled")
    op.drop_column("channels", "response_condensing_threshold")
    op.drop_column("channels", "response_condensing_keep_exact")
    op.drop_column("channels", "response_condensing_model")
    op.drop_column("channels", "response_condensing_prompt")
    op.drop_column("messages", "condensed")


def downgrade() -> None:
    op.add_column("messages", sa.Column("condensed", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column(
        "response_condensing_enabled", sa.Boolean(),
        server_default=sa.text("false"), nullable=False,
    ))
    op.add_column("channels", sa.Column("response_condensing_threshold", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("response_condensing_keep_exact", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("response_condensing_model", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("response_condensing_prompt", sa.Text(), nullable=True))
