"""Add `supports_image_generation` capability flag to provider_models.

Replaces the string-sniffing routing in ``app/tools/local/image.py`` (was:
``"gpt-image"``/``"dall-e"``/``"gemini"``/``"imagen"`` substring tests) with
an authoritative DB column, matching the Phase 5 pattern for
``supports_prompt_caching`` and ``supports_structured_output``.

Backfill covers the model id families currently routable from
``app/tools/local/image.py``:

  - GPT Image family: ``gpt-image-*`` (incl. ``gpt-image-1``, ``-mini``, ``-1.5``)
  - DALL-E family: ``dall-e-*``
  - Gemini native image: ``gemini-*-image*`` (e.g. ``gemini-2.5-flash-image``,
    ``gemini-2.0-flash-exp-image-generation``)
  - Imagen family: ``imagen-*``

Provider-prefixed forms (``openai/gpt-image-1``, ``google/gemini-2.5-flash-image``,
``gemini/gemini-2.5-flash-image``) are also matched so LiteLLM-routed rows pick
up the flag.

Revision ID: 246
Revises: 245
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "246"
down_revision = "245"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_models",
        sa.Column(
            "supports_image_generation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.execute(
        """
        UPDATE provider_models SET supports_image_generation = true
        WHERE model_id LIKE 'gpt-image-%'
           OR model_id LIKE 'openai/gpt-image-%'
           OR model_id LIKE 'dall-e-%'
           OR model_id LIKE 'openai/dall-e-%'
           OR model_id LIKE 'gemini-%-image%'
           OR model_id LIKE 'gemini/gemini-%-image%'
           OR model_id LIKE 'google/gemini-%-image%'
           OR model_id LIKE 'imagen-%'
           OR model_id LIKE 'google/imagen-%'
           OR model_id LIKE 'gemini/imagen-%'
        """
    )


def downgrade() -> None:
    op.drop_column("provider_models", "supports_image_generation")
