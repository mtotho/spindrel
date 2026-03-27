"""Convert single fallback model to ordered fallback models list.

Bots + Channels: migrate existing fallback_model/fallback_model_provider_id into
a new fallback_models JSONB list, then drop the old columns.
ChannelHeartbeats: add fallback_models JSONB.
New server_config table for global settings (global fallback list).

Revision ID: 097
Revises: 096
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "097"
down_revision = "096"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Bots ---
    op.add_column("bots", sa.Column(
        "fallback_models", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False,
    ))
    # Data-migrate existing single fallback into the new list
    op.execute("""
        UPDATE bots
        SET fallback_models = jsonb_build_array(
            jsonb_build_object('model', fallback_model, 'provider_id', fallback_model_provider_id)
        )
        WHERE fallback_model IS NOT NULL AND fallback_model != ''
    """)
    op.drop_column("bots", "fallback_model")
    op.drop_column("bots", "fallback_model_provider_id")

    # --- Channels ---
    op.add_column("channels", sa.Column(
        "fallback_models", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False,
    ))
    op.execute("""
        UPDATE channels
        SET fallback_models = jsonb_build_array(
            jsonb_build_object('model', fallback_model, 'provider_id', fallback_model_provider_id)
        )
        WHERE fallback_model IS NOT NULL AND fallback_model != ''
    """)
    op.drop_column("channels", "fallback_model")
    op.drop_column("channels", "fallback_model_provider_id")

    # --- ChannelHeartbeats ---
    op.add_column("channel_heartbeats", sa.Column(
        "fallback_models", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False,
    ))

    # --- ServerConfig singleton ---
    op.create_table(
        "server_config",
        sa.Column("id", sa.Text(), primary_key=True, server_default=sa.text("'default'")),
        sa.Column("global_fallback_models", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    # Seed the singleton row
    op.execute("INSERT INTO server_config (id) VALUES ('default') ON CONFLICT DO NOTHING")


def downgrade() -> None:
    # --- ServerConfig ---
    op.drop_table("server_config")

    # --- ChannelHeartbeats ---
    op.drop_column("channel_heartbeats", "fallback_models")

    # --- Channels ---
    op.add_column("channels", sa.Column("fallback_model", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("fallback_model_provider_id", sa.Text(), nullable=True))
    # Restore from first entry in fallback_models list
    op.execute("""
        UPDATE channels
        SET fallback_model = fallback_models->0->>'model',
            fallback_model_provider_id = fallback_models->0->>'provider_id'
        WHERE jsonb_array_length(fallback_models) > 0
    """)
    op.drop_column("channels", "fallback_models")

    # --- Bots ---
    op.add_column("bots", sa.Column("fallback_model", sa.Text(), nullable=True))
    op.add_column("bots", sa.Column(
        "fallback_model_provider_id", sa.Text(),
        sa.ForeignKey("provider_configs.id", ondelete="SET NULL"), nullable=True,
    ))
    op.execute("""
        UPDATE bots
        SET fallback_model = fallback_models->0->>'model',
            fallback_model_provider_id = fallback_models->0->>'provider_id'
        WHERE jsonb_array_length(fallback_models) > 0
    """)
    op.drop_column("bots", "fallback_models")
