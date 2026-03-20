"""Add port_mappings column to sandbox_profiles."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from typing import Sequence, Union

revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sandbox_profiles",
        sa.Column("port_mappings", JSONB(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("sandbox_profiles", "port_mappings")
