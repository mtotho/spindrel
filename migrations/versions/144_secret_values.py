"""Create secret_values table for encrypted env var vault.

Revision ID: 144
Revises: 143
"""

import sqlalchemy as sa
from alembic import op

revision = "144"
down_revision = "143"


def upgrade() -> None:
    op.create_table(
        "secret_values",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default=sa.text("''")),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.dialects.postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.dialects.postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("secret_values")
