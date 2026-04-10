"""Drop workspace_skills_enabled columns and remove workspace_skill documents.

The workspace skills system (file-based skill discovery from runtime workspace
filesystem) is being removed. It was redundant with three existing DB skill
loading paths (skills/, bots/{id}/skills/, integrations/{id}/skills/) which
all flow into the Skill table via file_sync.py. Bots wanting reference files
at runtime can read them via read_file — no separate skill abstraction needed.

Revision ID: 183
Revises: 182
"""
from alembic import op
import sqlalchemy as sa


revision = "183"
down_revision = "182"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Delete workspace skill rows from documents table.
    # The workspace_skills service stored embedded skills here with
    # source LIKE 'workspace_skill:%'.
    op.execute("DELETE FROM documents WHERE source LIKE 'workspace_skill:%'")

    # Drop the toggle columns.
    op.drop_column("channels", "workspace_skills_enabled")
    op.drop_column("shared_workspaces", "workspace_skills_enabled")


def downgrade() -> None:
    # Re-add the columns; document rows are not restored.
    op.add_column(
        "shared_workspaces",
        sa.Column(
            "workspace_skills_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "channels",
        sa.Column("workspace_skills_enabled", sa.Boolean(), nullable=True),
    )
