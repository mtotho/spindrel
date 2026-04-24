"""Drop obsolete bot base_prompt flag.

Revision ID: 243
Revises: 242
"""
from alembic import op
import sqlalchemy as sa

revision = "243"
down_revision = "242"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("bots", "base_prompt")


def downgrade():
    op.add_column(
        "bots",
        sa.Column("base_prompt", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
