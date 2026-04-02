"""Remove migration-seeded workspace schema templates (now shipped as integration files)

Templates are now sourced from integrations/mission_control/prompts/*.md
and synced via file_sync as source_type='integration'. The old migration-seeded
rows (source_type='manual') are removed to avoid duplicates.

FK on channels.workspace_schema_template_id is ON DELETE SET NULL, so existing
channels just lose their template selection (one-time re-select).

Revision ID: 134
Revises: 133
"""

from alembic import op
import sqlalchemy as sa


revision = "134"
down_revision = "133"


# The 7 deterministic UUIDs from migrations 124-126
_SEEDED_IDS = [
    "a0000000-0000-0000-0000-000000000001",  # Software Development
    "a0000000-0000-0000-0000-000000000002",  # Research / Analysis
    "a0000000-0000-0000-0000-000000000003",  # Creative Project
    "a0000000-0000-0000-0000-000000000004",  # General Project
    "a0000000-0000-0000-0000-000000000005",  # Project Management Hub
    "a0000000-0000-0000-0000-000000000006",  # Mission Control
    "a0000000-0000-0000-0000-000000000007",  # Software Testing / QA
]


def upgrade() -> None:
    for template_id in _SEEDED_IDS:
        op.execute(
            sa.text(
                "DELETE FROM prompt_templates WHERE id = CAST(:id AS uuid) AND source_type = 'manual'"
            ).bindparams(id=template_id)
        )


def downgrade() -> None:
    # Re-insert the templates as they existed after migration 126 (enriched content).
    # Only the minimal set needed — file_sync will overwrite if the files exist.
    _templates = [
        {
            "id": "a0000000-0000-0000-0000-000000000001",
            "name": "Software Development",
            "description": "Workspace schema for software projects — architecture docs, task tracking, and decision logs.",
            "category": "workspace_schema",
        },
        {
            "id": "a0000000-0000-0000-0000-000000000002",
            "name": "Research / Analysis",
            "description": "Workspace schema for research projects — question tracking, source management, and findings.",
            "category": "workspace_schema",
        },
        {
            "id": "a0000000-0000-0000-0000-000000000003",
            "name": "Creative Project",
            "description": "Workspace schema for creative projects — briefs, concepts, feedback, and timelines.",
            "category": "workspace_schema",
        },
        {
            "id": "a0000000-0000-0000-0000-000000000004",
            "name": "General Project",
            "description": "Generic workspace schema for any type of project.",
            "category": "workspace_schema",
        },
        {
            "id": "a0000000-0000-0000-0000-000000000005",
            "name": "Project Management Hub",
            "description": "Workspace schema for managing multiple projects across channels — status dashboards, cross-project tracking, and portfolio reporting.",
            "category": "workspace_schema",
        },
        {
            "id": "a0000000-0000-0000-0000-000000000006",
            "name": "Mission Control",
            "description": "Workspace schema with structured kanban task tracking, status reports, and decision logs.",
            "category": "workspace_schema",
        },
        {
            "id": "a0000000-0000-0000-0000-000000000007",
            "name": "Software Testing / QA",
            "description": "Workspace schema for test planning, case tracking, bug reports, and coverage analysis.",
            "category": "workspace_schema",
        },
    ]
    for t in _templates:
        op.execute(
            sa.text(
                "INSERT INTO prompt_templates (id, name, description, content, category, tags, source_type) "
                "VALUES (CAST(:id AS uuid), :name, :description, '', :category, '[]'::jsonb, 'manual') "
                "ON CONFLICT (id) DO NOTHING"
            ).bindparams(
                id=t["id"],
                name=t["name"],
                description=t["description"],
                category=t["category"],
            )
        )
