"""Add provider-model capability + foot-gun columns.

Adds:
  - context_window  (int, null)        - input cap; replaces ambiguous max_tokens for sizing
  - max_output_tokens  (int, null)     - output cap; copy max_tokens into here as starting point
  - supports_prompt_caching  (bool)    - explicit gate replacing string sniff in prompt_cache.py
  - cached_input_cost_per_1m  (text)   - cached read price, e.g. "$0.30" for Claude Sonnet
  - supports_structured_output  (bool) - response_format=json_schema gate (forward-looking)
  - extra_body  (jsonb)                - per-model extra_body merge (e.g. Ollama options.num_ctx)

Backfill:
  - max_output_tokens := max_tokens for existing rows (treat current value as output cap;
    admins can split into context_window vs max_output_tokens going forward).
  - supports_prompt_caching=true for Claude families, GPT-4o/5/Codex, Gemini 2.x.
  - supports_structured_output=true for OpenAI families and Gemini 2.x.

Revision ID: 245
Revises: 244
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "245"
down_revision = "244"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_models",
        sa.Column("context_window", sa.Integer(), nullable=True),
    )
    op.add_column(
        "provider_models",
        sa.Column("max_output_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "provider_models",
        sa.Column(
            "supports_prompt_caching",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "provider_models",
        sa.Column("cached_input_cost_per_1m", sa.Text(), nullable=True),
    )
    op.add_column(
        "provider_models",
        sa.Column(
            "supports_structured_output",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "provider_models",
        sa.Column(
            "extra_body",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.execute(
        "UPDATE provider_models SET max_output_tokens = max_tokens "
        "WHERE max_tokens IS NOT NULL"
    )

    op.execute(
        """
        UPDATE provider_models SET supports_prompt_caching = true
        WHERE model_id LIKE 'claude-%'
           OR model_id LIKE 'anthropic/claude-%'
           OR model_id LIKE 'gpt-4o%'
           OR model_id LIKE 'gpt-4.1%'
           OR model_id LIKE 'gpt-5%'
           OR model_id LIKE 'gpt-5.%'
           OR model_id LIKE 'openai/gpt-4o%'
           OR model_id LIKE 'openai/gpt-4.1%'
           OR model_id LIKE 'openai/gpt-5%'
           OR model_id LIKE 'codex-%'
           OR model_id LIKE 'openai/codex-%'
           OR model_id LIKE 'gpt-5-codex%'
           OR model_id LIKE 'gemini-2.%'
           OR model_id LIKE 'gemini/gemini-2.%'
           OR model_id LIKE 'google/gemini-2.%'
        """
    )

    op.execute(
        """
        UPDATE provider_models SET supports_structured_output = true
        WHERE model_id LIKE 'gpt-4o%'
           OR model_id LIKE 'gpt-4.1%'
           OR model_id LIKE 'gpt-5%'
           OR model_id LIKE 'gpt-5.%'
           OR model_id LIKE 'openai/gpt-4o%'
           OR model_id LIKE 'openai/gpt-4.1%'
           OR model_id LIKE 'openai/gpt-5%'
           OR model_id LIKE 'gemini-2.%'
           OR model_id LIKE 'gemini/gemini-2.%'
           OR model_id LIKE 'google/gemini-2.%'
        """
    )

    op.execute(
        """
        UPDATE provider_models SET cached_input_cost_per_1m = '$0.30'
        WHERE model_id LIKE 'claude-sonnet-%'
           OR model_id LIKE 'anthropic/claude-sonnet-%'
        """
    )
    op.execute(
        """
        UPDATE provider_models SET cached_input_cost_per_1m = '$1.50'
        WHERE model_id LIKE 'claude-opus-%'
           OR model_id LIKE 'anthropic/claude-opus-%'
        """
    )
    op.execute(
        """
        UPDATE provider_models SET cached_input_cost_per_1m = '$0.08'
        WHERE model_id LIKE 'claude-haiku-%'
           OR model_id LIKE 'anthropic/claude-haiku-%'
        """
    )


def downgrade() -> None:
    op.drop_column("provider_models", "extra_body")
    op.drop_column("provider_models", "supports_structured_output")
    op.drop_column("provider_models", "cached_input_cost_per_1m")
    op.drop_column("provider_models", "supports_prompt_caching")
    op.drop_column("provider_models", "max_output_tokens")
    op.drop_column("provider_models", "context_window")
