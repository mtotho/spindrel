"""Factory for Task."""
from __future__ import annotations

import uuid

from app.db.models import Task


def build_task(**overrides) -> Task:
    suffix = uuid.uuid4().hex[:8]
    defaults = dict(
        id=uuid.uuid4(),
        bot_id=f"bot-{suffix}",
        prompt=f"Test prompt {suffix}",
        status="pending",
        task_type="scheduled",
        dispatch_type="none",
    )
    return Task(**{**defaults, **overrides})
