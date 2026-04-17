"""Add widget_template_packages table for UI-configurable widget templates.

Templates can be edited and selected via the admin UI. Seed rows are
re-hydrated from YAML/integration manifests on every boot; user rows
override seeds when is_active.

Revision ID: 203
Revises: 202
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "203"
down_revision = "202"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "widget_template_packages",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("yaml_template", sa.Text(), nullable=False),
        sa.Column("python_code", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("is_readonly", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_orphaned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_invalid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("invalid_reason", sa.Text(), nullable=True),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.Column("source_integration", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("sample_payload", JSONB(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.CheckConstraint("source IN ('seed','user')", name="ck_wtp_source"),
        sa.CheckConstraint(
            "(source = 'seed') = is_readonly", name="ck_wtp_readonly_iff_seed",
        ),
        sa.CheckConstraint(
            "python_code IS NULL OR length(python_code) <= 200000",
            name="ck_wtp_python_code_size",
        ),
    )
    op.create_index(
        "ix_widget_template_packages_tool_name",
        "widget_template_packages", ["tool_name"],
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_widget_template_packages_active "
        "ON widget_template_packages (tool_name) WHERE is_active"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_widget_template_packages_seed_source "
        "ON widget_template_packages (tool_name, source_file, source_integration) "
        "WHERE source = 'seed'"
    )


def downgrade() -> None:
    op.drop_table("widget_template_packages")
