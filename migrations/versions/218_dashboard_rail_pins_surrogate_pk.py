"""Fix dashboard_rail_pins primary key — user_id cannot be nullable and PK.

PostgreSQL enforces NOT NULL on every PK column regardless of the DDL
nullable flag, so the ``scope='everyone'`` (user_id IS NULL) insert always
failed with an integrity error.

Fix: drop the composite PK on (dashboard_slug, user_id), add a surrogate
BIGSERIAL ``id`` column as the new PK.  Uniqueness is already enforced by the
two partial unique indexes (ix_drp_everyone / ix_drp_user).

Revision ID: 218
Revises: 217
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "218"
down_revision = "217"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the composite PK that forced user_id to be NOT NULL.
    op.drop_constraint(
        "dashboard_rail_pins_pkey", "dashboard_rail_pins", type_="primary"
    )
    # Add surrogate id as the new PK.
    op.add_column(
        "dashboard_rail_pins",
        sa.Column(
            "id", sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
        ),
    )
    op.create_primary_key("dashboard_rail_pins_pkey", "dashboard_rail_pins", ["id"])
    # Dropping the PK does not automatically remove the NOT NULL constraint
    # PostgreSQL placed on user_id when it was a PK column.
    op.alter_column("dashboard_rail_pins", "user_id", nullable=True)


def downgrade() -> None:
    op.drop_constraint("dashboard_rail_pins_pkey", "dashboard_rail_pins", type_="primary")
    op.drop_column("dashboard_rail_pins", "id")
    op.create_primary_key(
        "dashboard_rail_pins_pkey", "dashboard_rail_pins", ["dashboard_slug", "user_id"]
    )
