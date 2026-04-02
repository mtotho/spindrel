"""Add workspace_schema_content column + seed QA template + enrich all templates

Revision ID: 126
Revises: 125
"""

from alembic import op
import sqlalchemy as sa


revision = "126"
down_revision = "125"


# New template: Software Testing / QA
_QA_SCHEMA = {
    "id": "a0000000-0000-0000-0000-000000000007",
    "name": "Software Testing / QA",
    "description": "Workspace schema for test planning, case tracking, bug reports, and coverage analysis.",
    "category": "workspace_schema",
    "content": (
        "## Workspace File Organization — Software Testing / QA\n\n"
        "Organize channel workspace files to track testing activities:\n\n"
        "- **test-plan.md** — Test strategy and scope\n"
        "  - Features/modules under test, out-of-scope items\n"
        "  - Test types: unit, integration, E2E, regression, performance\n"
        "  - Environment requirements, test data needs\n"
        "  - Entry/exit criteria, risk areas\n\n"
        "- **test-cases.md** — Test case definitions\n"
        "  - Format: `### TC-NNN: Title` with steps, expected results, priority\n"
        "  - Group by feature or module using `## Feature Name` headers\n"
        "  - Mark status: draft, ready, automated, deprecated\n\n"
        "- **bugs.md** — Bug tracker\n"
        "  - Format: `### BUG-NNN: Title` with severity, steps to reproduce, expected vs actual\n"
        "  - Status: open, investigating, fixed, verified, closed\n"
        "  - Link to related test cases (TC-NNN references)\n\n"
        "- **coverage.md** — Test coverage analysis\n"
        "  - Coverage matrix: feature vs test type\n"
        "  - Gaps and untested areas\n"
        "  - Automation coverage percentage and targets\n\n"
        "- **results.md** — Test execution results\n"
        "  - Append new runs with date headers: `## YYYY-MM-DD Run`\n"
        "  - Summary: total/pass/fail/skip counts\n"
        "  - Failed test details and investigation notes\n\n"
        "- **notes.md** — Working notes and scratch space\n"
        "  - Environment quirks, workarounds, tribal knowledge\n"
        "  - Meeting notes from test planning/triage sessions\n\n"
        "Create files as needed — not all files are required from the start. "
        "Archive old test results and closed bugs to the archive/ folder."
    ),
}


# Enriched content for existing templates (keyed by UUID)
_ENRICHMENTS = {
    # Software Development
    "a0000000-0000-0000-0000-000000000001": (
        "## Workspace File Organization — Software Development\n\n"
        "Organize channel workspace files as follows:\n\n"
        "- **project.md** — Project overview\n"
        "  - Goals, scope, success criteria\n"
        "  - Tech stack and key dependencies\n"
        "  - Links to repos, CI/CD, staging/prod environments\n"
        "  - Team roles and contacts\n\n"
        "- **architecture.md** — System architecture\n"
        "  - High-level component diagram (describe in text/ASCII)\n"
        "  - Data flow between services\n"
        "  - Database schema overview and key relationships\n"
        "  - API contract summaries\n\n"
        "- **tasks.md** — Active tasks and status tracking\n"
        "  - Format: `### Task Title` with status, assignee, priority\n"
        "  - Group by milestone or sprint using `## Milestone` headers\n"
        "  - Move completed tasks to archive/ periodically\n\n"
        "- **decisions.md** — Architecture/design decisions (ADR-style)\n"
        "  - Format: `### ADR-NNN: Title` with Status, Context, Decision, Consequences\n"
        "  - Record alternatives considered and why they were rejected\n"
        "  - Date each decision for future reference\n\n"
        "- **notes.md** — Meeting notes, brainstorm captures, scratch work\n"
        "  - Date-stamp entries: `## YYYY-MM-DD Topic`\n"
        "  - Action items in bold or checklist format\n\n"
        "- **references.md** — External links, API docs, useful resources\n"
        "  - Categorize by topic (APIs, libraries, standards, tutorials)\n"
        "  - Add brief annotations explaining relevance\n\n"
        "Create files as needed — not all files are required from the start. "
        "Archive resolved items to the archive/ folder."
    ),
    # Research / Analysis
    "a0000000-0000-0000-0000-000000000002": (
        "## Workspace File Organization — Research / Analysis\n\n"
        "Organize channel workspace files as follows:\n\n"
        "- **question.md** — Research questions and hypotheses\n"
        "  - Primary question at the top, sub-questions as sub-headers\n"
        "  - State hypotheses clearly with testable predictions\n"
        "  - Track which questions are answered, open, or revised\n\n"
        "- **sources.md** — Source list with annotations\n"
        "  - Format: `### Source Title` with URL, author, date, relevance score\n"
        "  - Group by topic or type (papers, articles, datasets, interviews)\n"
        "  - Note credibility and potential biases\n\n"
        "- **findings.md** — Key findings and conclusions\n"
        "  - Link each finding to supporting evidence (source references)\n"
        "  - Distinguish between confirmed findings and tentative conclusions\n"
        "  - Note confidence level: high, medium, low\n\n"
        "- **methodology.md** — Research approach and frameworks\n"
        "  - Search strategy, inclusion/exclusion criteria\n"
        "  - Analysis frameworks and evaluation rubrics\n"
        "  - Limitations and assumptions\n\n"
        "- **notes.md** — Reading notes, raw observations, scratch work\n"
        "  - Date-stamp entries: `## YYYY-MM-DD Topic`\n"
        "  - Capture quotes and page references for later citation\n\n"
        "Create files as needed — not all files are required from the start. "
        "Archive completed investigations to the archive/ folder."
    ),
    # Creative Project
    "a0000000-0000-0000-0000-000000000003": (
        "## Workspace File Organization — Creative Project\n\n"
        "Organize channel workspace files as follows:\n\n"
        "- **brief.md** — Project brief\n"
        "  - Objectives and deliverables\n"
        "  - Target audience and their needs\n"
        "  - Constraints: budget, timeline, brand guidelines, technical limits\n"
        "  - Success metrics and acceptance criteria\n\n"
        "- **concepts.md** — Ideas, drafts, and iterations\n"
        "  - Version each concept: `### V1 — Concept Name`\n"
        "  - Note rationale for each direction explored\n"
        "  - Mark current working direction clearly\n"
        "  - Capture discarded ideas with reasons (may revisit later)\n\n"
        "- **feedback.md** — Review notes and revision requests\n"
        "  - Date-stamp each round: `## YYYY-MM-DD Review`\n"
        "  - Distinguish between mandatory changes and suggestions\n"
        "  - Track resolution: addressed, deferred, declined\n\n"
        "- **timeline.md** — Milestones, deadlines, and progress\n"
        "  - Key dates and deliverable deadlines\n"
        "  - Phase gates: concept → draft → review → final\n"
        "  - Buffer time and risk factors\n\n"
        "- **references.md** — Inspiration and style guides\n"
        "  - Mood boards, color palettes, typography choices\n"
        "  - Competitive examples and benchmarks\n"
        "  - Brand guidelines and asset locations\n\n"
        "Create files as needed — not all files are required from the start. "
        "Archive completed phases to the archive/ folder."
    ),
    # General Project
    "a0000000-0000-0000-0000-000000000004": (
        "## Workspace File Organization — General Project\n\n"
        "Organize channel workspace files as follows:\n\n"
        "- **overview.md** — Project overview\n"
        "  - Purpose and goals of this project\n"
        "  - Key context: who, what, why, when\n"
        "  - Success criteria and definition of done\n\n"
        "- **notes.md** — Working notes and scratch space\n"
        "  - Date-stamp entries: `## YYYY-MM-DD Topic`\n"
        "  - Observations, ideas, and open questions\n"
        "  - Action items in bold or checklist format\n\n"
        "- **tasks.md** — Active tasks and status tracking\n"
        "  - Format: `### Task Title` with status and priority\n"
        "  - Move completed tasks to archive/ periodically\n\n"
        "- **references.md** — Links, resources, and reference material\n"
        "  - Categorize by topic\n"
        "  - Add brief annotations explaining relevance\n\n"
        "Create files as needed — not all files are required from the start. "
        "Archive resolved items to the archive/ folder."
    ),
    # Project Management Hub
    "a0000000-0000-0000-0000-000000000005": (
        "## Workspace File Organization — Project Management Hub\n\n"
        "This channel is a management hub that tracks and coordinates work across multiple project channels.\n\n"
        "Organize workspace files as follows:\n\n"
        "- **dashboard.md** — Portfolio status overview\n"
        "  - One-line status for every active project channel\n"
        "  - Format: `| Project | Channel | Status | Health | Last Updated |`\n"
        "  - Update after each project review or status pull\n"
        "  - Health indicators: on-track, at-risk, blocked, completed\n\n"
        "- **projects.md** — Project registry\n"
        "  - Format: `### Project Name` with channel ID, owner, start date, schema type\n"
        "  - Current phase and next milestone\n"
        "  - Dependencies on other projects\n\n"
        "- **actions.md** — Cross-project action items\n"
        "  - Blockers and escalations requiring management attention\n"
        "  - Resource conflicts and reallocation decisions\n"
        "  - Format: `### ACTION-NNN: Title` with owner, deadline, status\n\n"
        "- **reports.md** — Periodic status reports and summaries\n"
        "  - Append new reports with date headers: `## YYYY-MM-DD Report`\n"
        "  - Include: highlights, risks, decisions needed\n"
        "  - Archive old reports when file grows large\n\n"
        "- **templates.md** — Reusable checklists and SOPs\n"
        "  - Project kickoff checklist\n"
        "  - Review criteria and quality gates\n"
        "  - Standard operating procedures\n\n"
        "- **retrospectives.md** — Lessons learned from completed projects\n"
        "  - Format: `### Project Name — YYYY-MM-DD`\n"
        "  - What went well, what didn't, what to change\n\n"
        "Use `list_workspace_channels` to discover all active project channels.\n"
        "Use `search_channel_workspace(query, channel_id=...)` to pull status from individual projects.\n"
        "When generating reports, pull live data from project channels rather than relying on stale dashboard entries.\n\n"
        "Scope control: by default, track all workspace-enabled channels. "
        "To limit scope, use the channel prompt (Settings > Prompt) to specify which projects to track.\n\n"
        "Archive completed project entries to the archive/ folder when projects close."
    ),
    # Mission Control
    "a0000000-0000-0000-0000-000000000006": (
        "## Workspace File Organization — Mission Control\n\n"
        "This channel uses the Mission Control protocol for structured task tracking.\n\n"
        "- **tasks.md** — Kanban board (columns: Backlog, In Progress, Review, Done)\n"
        "  - Use `create_task_card` and `move_task_card` tools for task management\n"
        "  - Card format: `### Card Title` followed by `- **key**: value` metadata lines\n"
        "  - Required metadata: status, priority, created date\n"
        "  - Optional: assignee, tags, due date, dependencies\n"
        "  - See the mission-control skill for full card format documentation\n\n"
        "- **status.md** — Project status and health\n"
        "  - Current sprint/iteration goals\n"
        "  - Health indicators: on-track, at-risk, blocked\n"
        "  - Active blockers and mitigation plans\n"
        "  - Milestone progress and upcoming deadlines\n\n"
        "- **notes.md** — Working notes and scratch space\n"
        "  - Date-stamp entries: `## YYYY-MM-DD Topic`\n"
        "  - Standup notes, brainstorm captures\n"
        "  - Action items in bold or checklist format\n\n"
        "- **decisions.md** — Decision log with rationale\n"
        "  - Format: `### DEC-NNN: Title` with Date, Context, Decision, Rationale\n"
        "  - Record alternatives considered\n"
        "  - Link to related task cards when applicable\n\n"
        "- **references.md** — Links and resources\n"
        "  - Categorize by topic\n"
        "  - Add brief annotations explaining relevance\n\n"
        "Create files as needed — not all files are required from the start. "
        "Use the `create_task_card` and `move_task_card` tools for task management.\n"
        "See the mission-control skill for full format documentation and conventions."
    ),
}


def upgrade() -> None:
    # 1. Add workspace_schema_content column
    op.add_column(
        "channels",
        sa.Column("workspace_schema_content", sa.Text(), nullable=True),
    )

    # 2. Seed QA template
    op.execute(
        sa.text(
            "INSERT INTO prompt_templates (id, name, description, content, category, tags, source_type) "
            "VALUES (CAST(:id AS uuid), :name, :description, :content, :category, '[]'::jsonb, 'manual') "
            "ON CONFLICT (id) DO NOTHING"
        ).bindparams(
            id=_QA_SCHEMA["id"],
            name=_QA_SCHEMA["name"],
            description=_QA_SCHEMA["description"],
            content=_QA_SCHEMA["content"],
            category=_QA_SCHEMA["category"],
        )
    )

    # 3. Enrich existing templates with detailed content
    for template_id, content in _ENRICHMENTS.items():
        op.execute(
            sa.text(
                "UPDATE prompt_templates SET content = :content WHERE id = CAST(:id AS uuid)"
            ).bindparams(id=template_id, content=content)
        )


def downgrade() -> None:
    op.drop_column("channels", "workspace_schema_content")

    # Remove QA template
    op.execute(
        sa.text("DELETE FROM prompt_templates WHERE id = CAST(:id AS uuid)").bindparams(
            id=_QA_SCHEMA["id"]
        )
    )

    # Note: we don't revert enrichments — they're safe to leave enriched
