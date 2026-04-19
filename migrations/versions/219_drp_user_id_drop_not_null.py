"""Drop NOT NULL on dashboard_rail_pins.user_id.

Migration 218 dropped the composite PK but did not remove the NOT NULL
constraint PostgreSQL implicitly placed on user_id when it was a PK column.
Dropping a PK in Postgres does not cascade to column-level NOT NULL.

Revision ID: 219
Revises: 218
"""
from __future__ import annotations

from alembic import op


revision = "219"
down_revision = "218"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("dashboard_rail_pins", "user_id", nullable=True)


def downgrade() -> None:
    op.alter_column("dashboard_rail_pins", "user_id", nullable=False)
