"""Add supports_reasoning column to provider_models.

Backfills `true` for known reasoning-capable model_ids (Claude Opus/Sonnet/Haiku-4.5,
gpt-5*, o1/o3/o4-*, codex-*, gemini-2.5-*, deepseek-reasoner / deepseek-r1*, grok-3-*).
Everything else defaults to `false`; admin toggles via the admin model-edit form.

Runtime authority: the DB flag is consulted by `filter_model_params` (to strip
reasoning kwargs for models that don't support it), by the bot editor UI (to grey
out the Reasoning effort control), and by the `/effort` slash command validator
(to reject `/effort high` on channels whose primary bot can't reason).

Revision ID: 242
Revises: 241
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "242"
down_revision = "241"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_models",
        sa.Column(
            "supports_reasoning",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Backfill known reasoning-capable models. Patterns cover both bare IDs
    # (`claude-opus-4-7`) and LiteLLM-prefixed IDs (`anthropic/claude-opus-4-7`).
    op.execute(
        """
        UPDATE provider_models SET supports_reasoning = true
        WHERE model_id LIKE 'claude-opus-%'
           OR model_id LIKE 'claude-sonnet-%'
           OR model_id LIKE 'claude-haiku-4-5%'
           OR model_id LIKE 'anthropic/claude-opus-%'
           OR model_id LIKE 'anthropic/claude-sonnet-%'
           OR model_id LIKE 'anthropic/claude-haiku-4-5%'
           OR model_id LIKE 'gpt-5%'
           OR model_id LIKE 'openai/gpt-5%'
           OR model_id LIKE 'o1%'
           OR model_id LIKE 'o3%'
           OR model_id LIKE 'o4%'
           OR model_id LIKE 'openai/o1%'
           OR model_id LIKE 'openai/o3%'
           OR model_id LIKE 'openai/o4%'
           OR model_id LIKE 'codex-%'
           OR model_id LIKE 'openai/codex-%'
           OR model_id LIKE 'gemini-2.5-%'
           OR model_id LIKE 'gemini/gemini-2.5-%'
           OR model_id LIKE 'google/gemini-2.5-%'
           OR model_id = 'deepseek-reasoner'
           OR model_id LIKE 'deepseek-r1%'
           OR model_id LIKE 'deepseek/deepseek-r1%'
           OR model_id LIKE 'grok-3-%'
           OR model_id LIKE 'xai/grok-3-%'
        """
    )


def downgrade() -> None:
    op.drop_column("provider_models", "supports_reasoning")
