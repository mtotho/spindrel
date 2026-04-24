"""Normalize post-reorg skill IDs to match filesystem paths.

After the 2026-04-24 skills reorganization, 21 files retained `id:` frontmatter
overrides so the logical ID (and thus enrollment FK) stayed stable across the
move. Those overrides have now been removed so path == ID everywhere. This
migration rewrites matching ``bot_skill_enrollment.skill_id`` and
``channel_skill_enrollment.skill_id`` rows from the old ID to the new
path-derived ID. The ``skills`` row itself is re-created by ``file_sync`` on the
next boot under the new ID; old rows are pruned by the missing-file sweep.

Revision ID: 244
Revises: 243
"""
from alembic import op
import sqlalchemy as sa

revision = "244"
down_revision = "243"
branch_labels = None
depends_on = None


RENAMES: list[tuple[str, str]] = [
    ("machine_control", "automation/machine_control"),
    ("standing_orders", "automation/standing_orders"),
    ("search_history", "history_and_memory/search_history"),
    ("shared/orchestrator", "orchestrator"),
    ("shared/orchestrator/audits", "orchestrator/audits"),
    ("shared/orchestrator/integration-builder", "orchestrator/integration_builder"),
    ("shared/orchestrator/model-efficiency", "orchestrator/model_efficiency"),
    ("shared/orchestrator/workspace-api-reference", "orchestrator/workspace_api_reference"),
    ("shared/orchestrator/workspace-delegation", "orchestrator/workspace_delegation"),
    ("shared/orchestrator/workspace-management", "orchestrator/workspace_management"),
    ("pipeline_authoring", "pipelines/authoring"),
    ("pipeline_creation", "pipelines/creation"),
    ("widgets/bot-callable-handlers", "widgets/bot_callable_handlers"),
    ("widget_dashboards", "widgets/channel_dashboards"),
    ("widgets/tool-dispatch", "widgets/tool_dispatch"),
    ("attachments", "workspace/attachments"),
    ("channel_workspaces", "workspace/channel_workspaces"),
    ("docker_stacks", "workspace/docker_stacks"),
    ("workspace_files", "workspace/files"),
    ("knowledge_bases", "workspace/knowledge_bases"),
    ("workspace_member", "workspace/member"),
]


TABLES = ("bot_skill_enrollment", "channel_skill_enrollment")


def _defer_fk(bind: sa.engine.Connection) -> None:
    dialect = bind.dialect.name
    if dialect == "postgresql":
        bind.execute(sa.text("SET session_replication_role = replica"))
    elif dialect == "sqlite":
        bind.execute(sa.text("PRAGMA foreign_keys = OFF"))


def _restore_fk(bind: sa.engine.Connection) -> None:
    dialect = bind.dialect.name
    if dialect == "postgresql":
        bind.execute(sa.text("SET session_replication_role = origin"))
    elif dialect == "sqlite":
        bind.execute(sa.text("PRAGMA foreign_keys = ON"))


def _rewrite(bind: sa.engine.Connection, pairs: list[tuple[str, str]]) -> None:
    for table in TABLES:
        # Skip tables that aren't present (fresh-install / partial-schema safety).
        inspector = sa.inspect(bind)
        if table not in inspector.get_table_names():
            continue
        for old, new in pairs:
            bind.execute(
                sa.text(
                    f"UPDATE {table} SET skill_id = :new "
                    f"WHERE skill_id = :old"
                ),
                {"old": old, "new": new},
            )


def upgrade() -> None:
    bind = op.get_bind()
    _defer_fk(bind)
    try:
        _rewrite(bind, RENAMES)
    finally:
        _restore_fk(bind)


def downgrade() -> None:
    bind = op.get_bind()
    _defer_fk(bind)
    try:
        _rewrite(bind, [(new, old) for old, new in RENAMES])
    finally:
        _restore_fk(bind)
