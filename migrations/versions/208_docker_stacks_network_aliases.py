"""Docker stacks: network_aliases column for multi-instance namespacing.

Part of the multi-instance stack collision fix. When multiple agent-server
instances (e.g. prod + e2e) share one Docker daemon, integration-declared
stacks would collide on globally-unique container_name / project_name.

The fix namespaces project_name with SPINDREL_INSTANCE_ID and wires
per-service DNS through `docker network connect --alias` instead of
container_name. Aliases are stored per-stack so the connect call can
replay them on restart.

Revision ID: 208
Revises: 207
"""
from alembic import op
import sqlalchemy as sa


revision = "208"
down_revision = "207"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
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
                    "network_aliases",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'{}'"),
                )
            )


def downgrade() -> None:
    with op.batch_alter_table("docker_stacks") as batch:
        batch.drop_column("network_aliases")
