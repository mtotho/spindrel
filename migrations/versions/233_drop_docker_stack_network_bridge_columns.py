"""Drop docker_stacks.connect_networks + docker_stacks.network_aliases.

Integration sidecar stacks no longer bridge into the agent network via a
post-``docker compose up`` ``docker network connect --alias`` step. The
wiring moved into the integration's ``docker-compose.yml`` itself via a
top-level ``networks: agent_net: external: true`` + per-service
``networks.agent_net.aliases: ["<svc>-${SPINDREL_INSTANCE_ID}"]`` block,
which compose re-applies on every restart. The two columns that cached
the imperative bridge inputs are no longer read or written, so drop them.

Revision ID: 233
Revises: 232
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "233"
down_revision = "232"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("docker_stacks") as batch:
        batch.drop_column("network_aliases")
        batch.drop_column("connect_networks")


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.add_column(
            "docker_stacks",
            sa.Column(
                "connect_networks",
                sa.dialects.postgresql.JSONB,
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )
        op.add_column(
            "docker_stacks",
            sa.Column(
                "network_aliases",
                sa.dialects.postgresql.JSONB,
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )
    else:
        with op.batch_alter_table("docker_stacks") as batch:
            batch.add_column(
                sa.Column(
                    "connect_networks",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'[]'"),
                )
            )
            batch.add_column(
                sa.Column(
                    "network_aliases",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'{}'"),
                )
            )
