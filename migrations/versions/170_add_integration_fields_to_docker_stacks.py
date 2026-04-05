"""Add integration fields to docker_stacks

- source: 'bot' or 'integration'
- integration_id: unique per integration (partial index)
- connect_networks: JSONB list of Docker networks to bridge into

Revision ID: 170
Revises: 169
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "170"
down_revision = "169"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "docker_stacks",
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'bot'")),
    )
    op.add_column(
        "docker_stacks",
        sa.Column("integration_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "docker_stacks",
        sa.Column(
            "connect_networks",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    # Partial unique index: only one stack per integration
    op.create_index(
        "ix_docker_stacks_integration_id_unique",
        "docker_stacks",
        ["integration_id"],
        unique=True,
        postgresql_where=sa.text("integration_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_docker_stacks_integration_id_unique", table_name="docker_stacks")
    op.drop_column("docker_stacks", "connect_networks")
    op.drop_column("docker_stacks", "integration_id")
    op.drop_column("docker_stacks", "source")
