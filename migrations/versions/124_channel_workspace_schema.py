"""Add workspace_schema_template_id to channels + seed workspace schema templates

Revision ID: 124
Revises: 123
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "124"
down_revision = "123"


# UUIDs for seeded workspace schema templates (deterministic for idempotency)
_SCHEMAS = [
    {
        "id": "a0000000-0000-0000-0000-000000000001",
        "name": "Software Development",
        "description": "Workspace schema for software projects — architecture docs, task tracking, and decision logs.",
        "category": "workspace_schema",
        "content": (
            "## Workspace File Organization — Software Development\n\n"
            "Organize channel workspace files as follows:\n\n"
            "- **project.md** — Project overview: goals, scope, tech stack, key links\n"
            "- **architecture.md** — System architecture, component design, data flow\n"
            "- **tasks.md** — Active tasks and status tracking\n"
            "- **decisions.md** — Architecture/design decisions with rationale (ADR-style)\n"
            "- **notes.md** — Meeting notes, brainstorm captures, scratch work\n"
            "- **references.md** — External links, API docs, useful resources\n\n"
            "Create files as needed — not all files are required from the start. "
            "Archive resolved items to the archive/ folder."
        ),
    },
    {
        "id": "a0000000-0000-0000-0000-000000000002",
        "name": "Research / Analysis",
        "description": "Workspace schema for research projects — question tracking, source management, and findings.",
        "category": "workspace_schema",
        "content": (
            "## Workspace File Organization — Research / Analysis\n\n"
            "Organize channel workspace files as follows:\n\n"
            "- **question.md** — Research questions and hypotheses to investigate\n"
            "- **sources.md** — Source list with annotations (papers, articles, data)\n"
            "- **findings.md** — Key findings, conclusions, and evidence\n"
            "- **methodology.md** — Research approach, criteria, frameworks used\n"
            "- **notes.md** — Reading notes, raw observations, scratch work\n\n"
            "Create files as needed — not all files are required from the start. "
            "Archive completed investigations to the archive/ folder."
        ),
    },
    {
        "id": "a0000000-0000-0000-0000-000000000003",
        "name": "Creative Project",
        "description": "Workspace schema for creative projects — briefs, concepts, feedback, and timelines.",
        "category": "workspace_schema",
        "content": (
            "## Workspace File Organization — Creative Project\n\n"
            "Organize channel workspace files as follows:\n\n"
            "- **brief.md** — Project brief: objectives, audience, constraints, deliverables\n"
            "- **concepts.md** — Ideas, drafts, iterations, and variations\n"
            "- **feedback.md** — Review notes, critique, revision requests\n"
            "- **timeline.md** — Milestones, deadlines, and progress tracking\n"
            "- **references.md** — Inspiration, mood boards, style guides, examples\n\n"
            "Create files as needed — not all files are required from the start. "
            "Archive completed phases to the archive/ folder."
        ),
    },
    {
        "id": "a0000000-0000-0000-0000-000000000004",
        "name": "General Project",
        "description": "Generic workspace schema for any type of project.",
        "category": "workspace_schema",
        "content": (
            "## Workspace File Organization — General Project\n\n"
            "Organize channel workspace files as follows:\n\n"
            "- **overview.md** — Project overview: purpose, goals, key context\n"
            "- **notes.md** — Working notes, observations, and scratch space\n"
            "- **tasks.md** — Active tasks and status tracking\n"
            "- **references.md** — Links, resources, and reference material\n\n"
            "Create files as needed — not all files are required from the start. "
            "Archive resolved items to the archive/ folder."
        ),
    },
    {
        "id": "a0000000-0000-0000-0000-000000000005",
        "name": "Project Management Hub",
        "description": "Workspace schema for managing multiple projects across channels — status dashboards, cross-project tracking, and portfolio reporting.",
        "category": "workspace_schema",
        "content": (
            "## Workspace File Organization — Project Management Hub\n\n"
            "This channel is a management hub that tracks and coordinates work across multiple project channels.\n\n"
            "Organize workspace files as follows:\n\n"
            "- **dashboard.md** — Portfolio status: one-line status for every active project channel, updated after each review\n"
            "- **projects.md** — Project registry: channel name, channel ID, owner, start date, current phase, schema type\n"
            "- **actions.md** — Cross-project action items, blockers, and escalations\n"
            "- **reports.md** — Periodic status reports and summaries (append new reports, archive old ones)\n"
            "- **templates.md** — Reusable checklists, review criteria, and standard operating procedures\n"
            "- **retrospectives.md** — Lessons learned from completed projects\n\n"
            "Use `list_workspace_channels` to discover all active project channels.\n"
            "Use `search_channel_workspace(query, channel_id=...)` to pull status from individual projects.\n"
            "When generating reports, pull live data from project channels rather than relying on stale dashboard entries.\n\n"
            "Scope control: by default, track all workspace-enabled channels. "
            "To limit scope, use the channel prompt (Settings > Prompt) to specify which projects to track, "
            "e.g. 'Only track: Henderson Remodel, Auth Rewrite, Brand Refresh'.\n\n"
            "Archive completed project entries to the archive/ folder when projects close."
        ),
    },
]


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column(
            "workspace_schema_template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("prompt_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Seed default workspace schema templates (idempotent — skip if already exists)
    for schema in _SCHEMAS:
        op.execute(
            sa.text(
                "INSERT INTO prompt_templates (id, name, description, content, category, tags, source_type) "
                "VALUES (CAST(:id AS uuid), :name, :description, :content, :category, '[]'::jsonb, 'manual') "
                "ON CONFLICT (id) DO NOTHING"
            ).bindparams(
                id=schema["id"],
                name=schema["name"],
                description=schema["description"],
                content=schema["content"],
                category=schema["category"],
            )
        )


def downgrade() -> None:
    op.drop_column("channels", "workspace_schema_template_id")

    # Remove seeded templates
    for schema in _SCHEMAS:
        op.execute(
            sa.text("DELETE FROM prompt_templates WHERE id = :id").bindparams(id=schema["id"])
        )
