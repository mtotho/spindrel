"""Add tool/skill override columns to channels.

Revision ID: 065
Revises: 064
Create Date: 2026-03-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None

_COLUMNS = [
    "local_tools_override",
    "local_tools_disabled",
    "mcp_servers_override",
    "mcp_servers_disabled",
    "client_tools_override",
    "client_tools_disabled",
    "pinned_tools_override",
    "skills_override",
    "skills_disabled",
]


def upgrade():
    for col in _COLUMNS:
        op.add_column("channels", sa.Column(col, JSONB, nullable=True))


def downgrade():
    for col in reversed(_COLUMNS):
        op.drop_column("channels", col)
