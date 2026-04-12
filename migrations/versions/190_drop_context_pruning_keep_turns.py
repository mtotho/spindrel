"""Drop context_pruning_keep_turns from bots and channels.

The setting became a no-op — all tool results from previous turns are
pruned regardless.  Clean up the dead columns.

Revision ID: 190
Revises: 189
"""

import sqlalchemy as sa
from alembic import op

revision: str = "190"
down_revision: str = "189"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.drop_column("bots", "context_pruning_keep_turns")
    op.drop_column("channels", "context_pruning_keep_turns")


def downgrade() -> None:
    op.add_column("channels", sa.Column("context_pruning_keep_turns", sa.Integer(), nullable=True))
    op.add_column("bots", sa.Column("context_pruning_keep_turns", sa.Integer(), nullable=True))
