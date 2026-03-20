"""Add parent_session_id, root_session_id, depth to sessions table.

Revision ID: 025
Revises: 024
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("parent_session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("root_session_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("depth", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_foreign_key(
        "fk_sessions_parent_session_id",
        "sessions",
        "sessions",
        ["parent_session_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_sessions_root_session_id",
        "sessions",
        "sessions",
        ["root_session_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sessions_root_session_id", "sessions", type_="foreignkey")
    op.drop_constraint("fk_sessions_parent_session_id", "sessions", type_="foreignkey")
    op.drop_column("sessions", "depth")
    op.drop_column("sessions", "root_session_id")
    op.drop_column("sessions", "parent_session_id")
