"""Add host_exec_config and filesystem_access columns to bots table."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from typing import Sequence, Union

revision: str = "017"
down_revision: Union[str, None] = "016_sandbox_many"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bots",
        sa.Column(
            "host_exec_config",
            JSONB(),
            nullable=False,
            server_default='{"enabled": false, "dry_run": false, "working_dirs": [], "commands": [], "blocked_patterns": [], "env_passthrough": [], "timeout": null, "max_output_bytes": null}',
        ),
    )
    op.add_column(
        "bots",
        sa.Column(
            "filesystem_access",
            JSONB(),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("bots", "filesystem_access")
    op.drop_column("bots", "host_exec_config")
