"""Workspace Singleton Cleanup — drop bots.workspace_only and rewrite source='auto'.

Two unrelated cleanups bundled because they're both housekeeping for the
Workspace Singleton Cleanup track:

1. **Drop `bots.workspace_only`.** Added in migration 131 to hide
   workspace-specific bots from the global channel view. In single-workspace
   mode (every bot is a member of the singular default workspace), the
   distinction has no meaning, and no UI surface ever shipped a filter that
   read this flag. The field has been a no-op since it was added.

2. **Rewrite `bot_skill_enrollment.source = 'auto'` rows to `'starter'`.**
   Session 12's commit added a `source='auto'` value for conditional
   workspace-bot skill enrollment. Session 13 deleted the enrollment block
   that produced those rows, and the singleton-cleanup pass dropped the
   `'auto'` value from the `EnrollmentSource` Literal entirely. Any rows that
   were written in between get rewritten to `'starter'` so the UI keeps
   rendering them (the EnrolledSkillsPanel `sourceOrder` no longer includes
   `'auto'`, so unmigrated rows would silently disappear from the working-set
   view). The targeted skills (`workspace_member`, `channel_workspaces`,
   `docker_stacks`) are now in `STARTER_SKILL_IDS` anyway, so `'starter'` is
   the semantically correct label.

Revision ID: 186
Revises: 185
"""
from alembic import op
import sqlalchemy as sa


revision = "186"
down_revision = "185"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Rewrite source='auto' rows to 'starter'. Safe on both dialects.
    op.execute(
        "UPDATE bot_skill_enrollment SET source = 'starter' WHERE source = 'auto'"
    )

    # 2. Drop bots.workspace_only.
    # SQLite (unit tests) may not have the column on a fresh schema since the
    # model no longer declares it. Guard the drop.
    if bind.dialect.name == "sqlite":
        cols = {row[1] for row in bind.execute(sa.text("PRAGMA table_info(bots)")).fetchall()}
        if "workspace_only" not in cols:
            return
    op.drop_column("bots", "workspace_only")


def downgrade() -> None:
    # Restore the column. The source='auto' rewrite is intentionally not
    # reversed — there's no way to know which rows were originally 'auto'.
    op.add_column(
        "bots",
        sa.Column(
            "workspace_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
