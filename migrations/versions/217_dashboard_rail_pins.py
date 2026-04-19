"""Per-user rail pinning for widget dashboards.

Splits the single ``widget_dashboards.pin_to_rail`` / ``rail_position``
columns into a new junction table ``dashboard_rail_pins`` so the same
dashboard can be pinned to the rail for everyone (``user_id IS NULL``)
AND for individual users (``user_id = uuid``) independently.

Any existing ``pin_to_rail=TRUE`` dashboard becomes a single NULL-user
("everyone") row so the sidebar keeps looking identical after the
migration.

Admin-only enforcement of "everyone" scope lives in the service layer
(``app/services/dashboard_rail.py``), not in a DB constraint — the
junction table just stores the mapping.

Revision ID: 217
Revises: 216
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID


revision = "217"
down_revision = "216"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_rail_pins",
        sa.Column(
            "dashboard_slug", sa.Text(),
            sa.ForeignKey(
                "widget_dashboards.slug",
                ondelete="CASCADE", onupdate="CASCADE",
            ),
            primary_key=True, nullable=False,
        ),
        # NULL user_id represents the "for everyone" row. A primary-key column
        # can be NULL in Postgres when the PK is composite — pair with partial
        # unique indexes below to express the real uniqueness contract.
        sa.Column(
            "user_id", PgUUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True, nullable=True,
        ),
        sa.Column("rail_position", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    # Partial unique indexes give the real contract:
    #   - at most one "everyone" row per dashboard
    #   - at most one personal row per (dashboard, user)
    op.create_index(
        "ix_drp_everyone", "dashboard_rail_pins", ["dashboard_slug"],
        unique=True, postgresql_where=sa.text("user_id IS NULL"),
    )
    op.create_index(
        "ix_drp_user", "dashboard_rail_pins", ["dashboard_slug", "user_id"],
        unique=True, postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_drp_user_id", "dashboard_rail_pins", ["user_id"],
    )

    # Backfill every currently-rail-pinned dashboard as a NULL-user row so
    # the sidebar doesn't lose entries on upgrade.
    conn = op.get_bind()
    conn.execute(sa.text(
        "INSERT INTO dashboard_rail_pins (dashboard_slug, user_id, rail_position) "
        "SELECT slug, NULL, rail_position FROM widget_dashboards "
        "WHERE pin_to_rail = TRUE"
    ))

    op.drop_column("widget_dashboards", "rail_position")
    op.drop_column("widget_dashboards", "pin_to_rail")


def downgrade() -> None:
    """Restore the legacy single-row rail columns.

    Personal ("just me") rows are dropped — only NULL-user rows carry over.
    Flagged in the track plan; acceptable for a dev-box rollback.
    """
    op.add_column(
        "widget_dashboards",
        sa.Column(
            "pin_to_rail", sa.Boolean(),
            server_default=sa.text("false"), nullable=False,
        ),
    )
    op.add_column(
        "widget_dashboards",
        sa.Column("rail_position", sa.Integer(), nullable=True),
    )

    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE widget_dashboards SET pin_to_rail = TRUE, "
        "rail_position = drp.rail_position "
        "FROM dashboard_rail_pins drp "
        "WHERE drp.dashboard_slug = widget_dashboards.slug "
        "AND drp.user_id IS NULL"
    ))

    op.drop_index("ix_drp_user_id", table_name="dashboard_rail_pins")
    op.drop_index("ix_drp_user", table_name="dashboard_rail_pins")
    op.drop_index("ix_drp_everyone", table_name="dashboard_rail_pins")
    op.drop_table("dashboard_rail_pins")
