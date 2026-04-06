"""Drop api_docs_mode column from bots — replaced by list_api_endpoints + call_api tools.

Revision ID: 177
Revises: 176
"""
from alembic import op
import sqlalchemy as sa

revision = "177"
down_revision = "176"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("bots", "api_docs_mode")


def downgrade() -> None:
    op.add_column("bots", sa.Column("api_docs_mode", sa.Text(), nullable=True))
