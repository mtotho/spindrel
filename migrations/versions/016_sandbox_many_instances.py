"""Allow many sandbox instances per profile (profile is a template only)."""
from typing import Sequence, Union

from alembic import op

revision: str = "016_sandbox_many"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_sandbox_instance_scope", "sandbox_instances", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_sandbox_instance_scope",
        "sandbox_instances",
        ["profile_id", "scope_type", "scope_key"],
    )
