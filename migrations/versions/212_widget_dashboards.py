"""Named widget dashboards — multi-dashboard support.

P6 of the Widget Dashboard track. Creates ``widget_dashboards`` (slug-keyed),
seeds a ``default`` row so existing pins stay valid, and promotes
``widget_dashboard_pins.dashboard_key`` into a real foreign key with
``ON DELETE CASCADE`` so deleting a dashboard removes its pins.

Revision ID: 212
Revises: 211
"""
from alembic import op
import sqlalchemy as sa

revision = "212"
down_revision = "211"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "widget_dashboards",
        sa.Column("slug", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("icon", sa.Text(), nullable=True),
        sa.Column(
            "pin_to_rail", sa.Boolean(), nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("rail_position", sa.Integer(), nullable=True),
        sa.Column(
            "last_viewed_at", sa.TIMESTAMP(timezone=True), nullable=True,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    # Seed 'default' so the existing FK on dashboard_key (and existing pins)
    # stay valid.
    op.execute(
        """
        INSERT INTO widget_dashboards (slug, name, icon, pin_to_rail)
        VALUES ('default', 'Default', 'LayoutDashboard', false)
        """
    )
    # Backfill any stray dashboard_key values onto the 'default' dashboard
    # before the FK is enforced.
    op.execute(
        """
        UPDATE widget_dashboard_pins
        SET dashboard_key = 'default'
        WHERE dashboard_key NOT IN (SELECT slug FROM widget_dashboards)
        """
    )
    op.create_foreign_key(
        "fk_widget_dashboard_pins_dashboard_key",
        "widget_dashboard_pins",
        "widget_dashboards",
        ["dashboard_key"],
        ["slug"],
        ondelete="CASCADE",
        onupdate="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_widget_dashboard_pins_dashboard_key",
        "widget_dashboard_pins",
        type_="foreignkey",
    )
    op.drop_table("widget_dashboards")
