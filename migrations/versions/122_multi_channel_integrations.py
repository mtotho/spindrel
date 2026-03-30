"""Allow same client_id in multiple channels (multi-channel fan-out).

Drop global UNIQUE on channel_integrations.client_id, replace with
composite UNIQUE on (channel_id, client_id) to prevent duplicate
bindings within the same channel while allowing the same repo/source
to be bound to multiple channels.

Revision ID: 122
Revises: 121
"""
from alembic import op

revision = "122"
down_revision = "121"


def upgrade() -> None:
    op.drop_constraint("channel_integrations_client_id_key", "channel_integrations", type_="unique")
    op.create_unique_constraint(
        "uq_channel_integrations_channel_client",
        "channel_integrations",
        ["channel_id", "client_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_channel_integrations_channel_client", "channel_integrations", type_="unique")
    op.create_unique_constraint("channel_integrations_client_id_key", "channel_integrations", ["client_id"])
