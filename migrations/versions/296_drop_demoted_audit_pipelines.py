"""drop demoted orchestrator audit pipelines

Revision ID: 296_drop_demoted_audit_pipelines
Revises: 295_turn_feedback
Create Date: 2026-05-03

Removes the four demoted system pipeline definition rows so that fresh
deploys and existing instances converge after their YAML files were
deleted from ``app/data/system_pipelines/``.

The seeder in ``app/services/task_seeding.py`` only inserts/refreshes
rows from YAML; it does not tombstone rows whose YAML disappeared. This
migration closes that gap by deleting the four definitions by their
deterministic ``pipeline_uuid()`` ids.

Cascade behavior:
- ``channel_pipeline_subscriptions.task_id`` is FK ON DELETE CASCADE, so
  any subscriptions to the deleted definitions go with them.
- Child run rows reference the parent through a plain ``parent_task_id``
  UUID column (no FK), so historical runs remain intact as orphan rows
  for admin history purposes.
"""
from __future__ import annotations

import uuid

from alembic import op


revision = "296_drop_demoted_audit_pipelines"
down_revision = "295_turn_feedback"
branch_labels = None
depends_on = None


# Mirrors ``app.services.task_seeding._PIPELINE_NAMESPACE``. Do not change.
_PIPELINE_NAMESPACE = uuid.UUID("6f9e2a4c-7e2f-5b9a-b2e1-1a3c7d9b0e42")

_DEMOTED_SLUGS = (
    "orchestrator.analyze_skill_quality",
    "orchestrator.analyze_memory_quality",
    "orchestrator.analyze_tool_usage",
    "orchestrator.analyze_costs",
)


def _row_id(slug: str) -> str:
    return str(uuid.uuid5(_PIPELINE_NAMESPACE, slug))


def upgrade() -> None:
    bind = op.get_bind()
    ids = [_row_id(slug) for slug in _DEMOTED_SLUGS]
    bind.exec_driver_sql(
        "DELETE FROM tasks WHERE id = ANY(%s::uuid[]) AND source = 'system'",
        (ids,),
    )


def downgrade() -> None:
    # Definitions are sourced from YAML; rerunning the seeder cannot
    # restore the deleted bodies because the YAML files were removed.
    # Downgrade is a no-op.
    pass
