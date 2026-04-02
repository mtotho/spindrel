"""Add session_mode column to workflows table.

Fixes missing column when migration 146 was applied before session_mode
was added to the table definition.

Revision ID: 147
Revises: 146
"""

import sqlalchemy as sa
from alembic import op

revision = "147"
down_revision = "146"


def upgrade() -> None:
    # Column may already exist if migration 146 was applied after session_mode
    # was added to the create_table definition.
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'workflows' AND column_name = 'session_mode'"
        )
    ).fetchone()
    if not result:
        op.add_column(
            "workflows",
            sa.Column("session_mode", sa.Text(), nullable=False, server_default=sa.text("'isolated'")),
        )


def downgrade() -> None:
    op.drop_column("workflows", "session_mode")
