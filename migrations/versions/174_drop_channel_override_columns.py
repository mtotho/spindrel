"""Drop channel whitelist override columns (Phase D simplification).

Removes: skills_override, local_tools_override, mcp_servers_override,
client_tools_override, pinned_tools_override. Only _disabled/_extra remain.

Revision ID: 174
Revises: 173
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "174"
down_revision = "173"
branch_labels = None
depends_on = None

_COLUMNS = [
    "skills_override",
    "local_tools_override",
    "mcp_servers_override",
    "client_tools_override",
    "pinned_tools_override",
]


def upgrade() -> None:
    for col in _COLUMNS:
        op.drop_column("channels", col)


def downgrade() -> None:
    for col in _COLUMNS:
        op.add_column("channels", sa.Column(col, JSONB, nullable=True))
