"""Drop carapaces.skills column.

The carapace `skills:` field is obsolete. Skills live in the per-bot working
set (`bot_skill_enrollment`); carapace prompt fragments surface them via
`get_skill('id')` pointers in their Deep Knowledge tables. The runtime merge
that flowed `carapace.skills` into `bot.skills` per turn was the structural
twin of `SharedWorkspace.skills` (dropped in migration 185) — a parallel
assignment surface that bypassed the working-set system entirely.

The 7 integration carapace YAMLs in the repo had their `skills:` blocks
removed; their fragments already had Deep Knowledge tables covering every
declared skill, so there is no behavior change at the agent layer.

Revision ID: 187
Revises: 186
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "187"
down_revision = "186"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # SQLite (used in unit tests) may not have the column at all on a fresh
    # schema since the model no longer declares it. Guard the drop.
    if bind.dialect.name == "sqlite":
        cols = {row[1] for row in bind.execute(sa.text("PRAGMA table_info(carapaces)")).fetchall()}
        if "skills" not in cols:
            return
    op.drop_column("carapaces", "skills")


def downgrade() -> None:
    op.add_column(
        "carapaces",
        sa.Column("skills", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
