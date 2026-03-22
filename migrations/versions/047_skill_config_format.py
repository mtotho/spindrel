"""Convert Bot.skills from flat string list to structured SkillConfig format.

Revision ID: 047
Revises: 046
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "047"
down_revision: Union[str, None] = "046"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # Convert ["id1", "id2"] to [{"id": "id1", "mode": "on_demand"}, ...]
    # Only update rows where skills is a non-empty array with string elements
    op.execute(sa.text("""
        UPDATE bots
        SET skills = (
            SELECT jsonb_agg(
                jsonb_build_object('id', elem::text, 'mode', 'on_demand')
            )
            FROM jsonb_array_elements_text(skills) AS elem
        )
        WHERE skills IS NOT NULL
          AND jsonb_array_length(skills) > 0
          AND jsonb_typeof(skills->0) = 'string'
    """))


def downgrade() -> None:
    # Convert back: [{"id": "id1", "mode": "..."}, ...] to ["id1", ...]
    op.execute(sa.text("""
        UPDATE bots
        SET skills = (
            SELECT jsonb_agg(elem->>'id')
            FROM jsonb_array_elements(skills) AS elem
        )
        WHERE skills IS NOT NULL
          AND jsonb_array_length(skills) > 0
          AND jsonb_typeof(skills->0) = 'object'
    """))
