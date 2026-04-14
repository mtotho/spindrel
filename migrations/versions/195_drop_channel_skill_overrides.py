"""Drop skills_disabled and skills_extra from channels.

Channel-level skill overrides are removed as part of Skill Simplification
Phase 4 (channel half). Per-bot enrollment via bot_skill_enrollment is the
canonical skill assignment surface. The UI already stopped reading/writing
these fields; this migration drops the columns.

Revision ID: 195
Revises: 194
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "195"
down_revision = "194"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("channels", "skills_disabled")
    op.drop_column("channels", "skills_extra")


def downgrade() -> None:
    op.add_column("channels", sa.Column("skills_extra", JSONB, nullable=True))
    op.add_column("channels", sa.Column("skills_disabled", JSONB, nullable=True))
