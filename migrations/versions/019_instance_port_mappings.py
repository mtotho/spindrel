"""Add port_mappings column to sandbox_instances."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from typing import Sequence, Union

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sandbox_instances",
        sa.Column("port_mappings", JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("sandbox_instances", "port_mappings")
