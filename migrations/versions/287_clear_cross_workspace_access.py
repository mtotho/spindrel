"""Clear stale cross_workspace_access flags from bot delegation_config.

The ``cross_workspace_access`` flag was retired by the channel-participant
rewrite — it's now metadata-only and rejected on writes (see
``app/tools/local/admin_bots.py``). Old bot rows can still carry the
key in ``delegation_config``; this migration pops it out so the
``bots_with_cross_workspace_access`` security audit signal goes silent.

One-way migration. Downgrade is intentionally a no-op — we don't restore
deprecated state.

Revision ID: 287_clear_cross_workspace_access
Revises: 286_dep_stack_blueprint
Create Date: 2026-05-01
"""
from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "287_clear_cross_workspace_access"
down_revision = "286_dep_stack_blueprint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    rows = conn.execute(
        sa.text(
            "SELECT id, delegation_config FROM bots "
            "WHERE delegation_config IS NOT NULL "
            "AND delegation_config::text LIKE '%cross_workspace_access%'"
        )
    ).fetchall()

    cleaned = 0
    for row in rows:
        config = row.delegation_config
        if not isinstance(config, dict):
            try:
                config = json.loads(config) if config else {}
            except (TypeError, ValueError):
                continue
        if "cross_workspace_access" not in config:
            continue
        config.pop("cross_workspace_access", None)
        conn.execute(
            sa.text("UPDATE bots SET delegation_config = :val WHERE id = :id"),
            {"val": json.dumps(config), "id": row.id},
        )
        cleaned += 1

    if cleaned:
        print(f"Cleared cross_workspace_access from {cleaned} bot row(s)")


def downgrade() -> None:
    # No-op — we don't restore deprecated state.
    pass
