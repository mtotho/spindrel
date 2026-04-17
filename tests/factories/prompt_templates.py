"""Factory for PromptTemplate."""
from __future__ import annotations

import uuid

from app.db.models import PromptTemplate


def build_prompt_template(**overrides) -> PromptTemplate:
    suffix = uuid.uuid4().hex[:8]
    defaults = dict(
        id=uuid.uuid4(),
        name=f"template-{suffix}",
        content="Test prompt content.",
        tags=[],
    )
    return PromptTemplate(**{**defaults, **overrides})
