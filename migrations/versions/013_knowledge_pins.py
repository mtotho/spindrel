"""Knowledge pins table.

Revision ID: 013
Revises: 012
Create Date: 2026-03-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_pins",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("knowledge_name", sa.Text(), nullable=False),
        sa.Column("bot_id", sa.Text(), nullable=True),
        sa.Column("client_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("bot_id IS NOT NULL OR client_id IS NOT NULL", name="ck_knowledge_pins_scope"),
    )
    # Unique constraint using COALESCE so (name, bot_A, NULL) is treated as unique
    op.execute("""
        CREATE UNIQUE INDEX uq_knowledge_pins
        ON knowledge_pins (knowledge_name, COALESCE(bot_id, ''), COALESCE(client_id, ''))
    """)
    op.create_index("ix_knowledge_pins_bot_id", "knowledge_pins", ["bot_id"])
    op.create_index("ix_knowledge_pins_client_id", "knowledge_pins", ["client_id"])


def downgrade() -> None:
    op.drop_table("knowledge_pins")
