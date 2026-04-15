"""Add skill review job columns and extra_instructions to bots table.

Splits the monolithic memory hygiene job into two independent job types:
- Memory maintenance (existing memory_hygiene_* columns)
- Skill review (new skill_review_* columns)

Also adds extra_instructions columns for both job types — appended to
the built-in prompt without replacing it.

Revision ID: 198
Revises: 197
"""
from alembic import op
import sqlalchemy as sa

revision = "198"
down_revision = "197"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Skill review job columns (parallel to memory_hygiene_*)
    op.add_column("bots", sa.Column("skill_review_enabled", sa.Boolean(), nullable=True))
    op.add_column("bots", sa.Column("skill_review_interval_hours", sa.Integer(), nullable=True))
    op.add_column("bots", sa.Column("skill_review_prompt", sa.Text(), nullable=True))
    op.add_column("bots", sa.Column("skill_review_only_if_active", sa.Boolean(), nullable=True))
    op.add_column("bots", sa.Column("skill_review_model", sa.Text(), nullable=True))
    op.add_column("bots", sa.Column("skill_review_model_provider_id", sa.Text(), nullable=True))
    op.add_column("bots", sa.Column("skill_review_target_hour", sa.Integer(), nullable=True))
    op.add_column("bots", sa.Column("last_skill_review_run_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column("bots", sa.Column("next_skill_review_run_at", sa.TIMESTAMP(timezone=True), nullable=True))

    # Extra instructions columns (appended to base prompt, not a full override)
    op.add_column("bots", sa.Column("memory_hygiene_extra_instructions", sa.Text(), nullable=True))
    op.add_column("bots", sa.Column("skill_review_extra_instructions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bots", "skill_review_extra_instructions")
    op.drop_column("bots", "memory_hygiene_extra_instructions")
    op.drop_column("bots", "next_skill_review_run_at")
    op.drop_column("bots", "last_skill_review_run_at")
    op.drop_column("bots", "skill_review_target_hour")
    op.drop_column("bots", "skill_review_model_provider_id")
    op.drop_column("bots", "skill_review_model")
    op.drop_column("bots", "skill_review_only_if_active")
    op.drop_column("bots", "skill_review_prompt")
    op.drop_column("bots", "skill_review_interval_hours")
    op.drop_column("bots", "skill_review_enabled")
