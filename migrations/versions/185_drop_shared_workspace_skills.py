"""Drop shared_workspaces.skills column.

The workspace-level "DB Skills" surface (manually pinning catalog skills onto
every bot in a workspace) is obsolete. Phase 3 (per-bot working set, see
migration 184) replaces it: every bot gets a starter pack at creation, fetches
promote on success, and the semantic discovery layer surfaces unenrolled
catalog skills on demand. The workspace-wide pin is redundant — and the
"pinned" mode it stored was already killed in earlier skill simplification
phases.

This is the workspace-level companion to the channel-level Phase 4 cleanup
(`channels.skills_extra` / `skills_disabled`), completed in migration 195.

Revision ID: 185
Revises: 184
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "185"
down_revision = "184"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # SQLite (used in unit tests) may not have the column at all on a fresh
    # schema since the model no longer declares it. Guard the drop.
    if bind.dialect.name == "sqlite":
        cols = {row[1] for row in bind.execute(sa.text("PRAGMA table_info(shared_workspaces)")).fetchall()}
        if "skills" not in cols:
            return
    op.drop_column("shared_workspaces", "skills")


def downgrade() -> None:
    op.add_column(
        "shared_workspaces",
        sa.Column("skills", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
