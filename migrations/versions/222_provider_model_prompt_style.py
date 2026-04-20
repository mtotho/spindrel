"""Add prompt_style column to provider_models.

Backfills based on the owning provider's type:
  - anthropic  → 'xml'
  - everything else (openai / openai-compatible / openai-subscription /
    anthropic-compatible / anthropic-subscription / litellm / ollama) → 'markdown'

Admin can override per-model from the admin UI.

Revision ID: 222
Revises: 221
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "222"
down_revision = "221"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_models",
        sa.Column(
            "prompt_style",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'markdown'"),
        ),
    )

    op.execute(
        """
        UPDATE provider_models
        SET prompt_style = 'xml'
        WHERE provider_id IN (
            SELECT id FROM provider_configs WHERE provider_type = 'anthropic'
        )
        """
    )


def downgrade() -> None:
    op.drop_column("provider_models", "prompt_style")
