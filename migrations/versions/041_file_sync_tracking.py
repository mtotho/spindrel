"""Add file-sync tracking columns.

skills: source_path, source_type
bot_knowledge: source_path, source_type, editable_from_tool
tool_embeddings: source_integration, source_file

Revision ID: 041
Revises: 040
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "041"
down_revision: Union[str, None] = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("skills", sa.Column("source_path", sa.Text(), nullable=True))
    op.add_column(
        "skills",
        sa.Column(
            "source_type",
            sa.Text(),
            nullable=False,
            server_default="manual",
        ),
    )

    op.add_column("bot_knowledge", sa.Column("source_path", sa.Text(), nullable=True))
    op.add_column(
        "bot_knowledge",
        sa.Column(
            "source_type",
            sa.Text(),
            nullable=False,
            server_default="tool",
        ),
    )
    op.add_column(
        "bot_knowledge",
        sa.Column(
            "editable_from_tool",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )

    op.add_column("tool_embeddings", sa.Column("source_integration", sa.Text(), nullable=True))
    op.add_column("tool_embeddings", sa.Column("source_file", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tool_embeddings", "source_file")
    op.drop_column("tool_embeddings", "source_integration")

    op.drop_column("bot_knowledge", "editable_from_tool")
    op.drop_column("bot_knowledge", "source_type")
    op.drop_column("bot_knowledge", "source_path")

    op.drop_column("skills", "source_type")
    op.drop_column("skills", "source_path")
