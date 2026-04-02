"""Seed Mission Control workspace schema template

Revision ID: 125
Revises: 124
"""

from alembic import op
import sqlalchemy as sa


revision = "125"
down_revision = "124"


_SCHEMA = {
    "id": "a0000000-0000-0000-0000-000000000006",
    "name": "Mission Control",
    "description": "Workspace schema with structured kanban task tracking, status reports, and decision logs.",
    "category": "workspace_schema",
    "content": (
        "## Workspace File Organization — Mission Control\n\n"
        "This channel uses the Mission Control protocol for structured task tracking.\n\n"
        "- **tasks.md** — Kanban board (columns: Backlog, In Progress, Review, Done)\n"
        "- **status.md** — Project status, health, blockers, milestones\n"
        "- **notes.md** — Working notes and scratch space\n"
        "- **decisions.md** — Decision log with rationale\n"
        "- **references.md** — Links and resources\n\n"
        "Use the `create_task_card` and `move_task_card` tools for task management.\n"
        "Tasks use structured markdown format — see the mission-control skill for details."
    ),
}


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO prompt_templates (id, name, description, content, category, tags, source_type) "
            "VALUES (CAST(:id AS uuid), :name, :description, :content, :category, '[]'::jsonb, 'manual') "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(
            id=_SCHEMA["id"],
            name=_SCHEMA["name"],
            description=_SCHEMA["description"],
            content=_SCHEMA["content"],
            category=_SCHEMA["category"],
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM prompt_templates WHERE id = :id").bindparams(id=_SCHEMA["id"])
    )
