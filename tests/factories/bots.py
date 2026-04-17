"""Factory for app.db.models.Bot."""
from __future__ import annotations

import uuid

from app.db.models import Bot


def build_bot(**overrides) -> Bot:
    suffix = uuid.uuid4().hex[:8]
    defaults = dict(
        id=f"bot-{suffix}",
        name=f"Test Bot {suffix}",
        model="test/model",
        system_prompt="You are a test bot.",
        memory_scheme="workspace-files",
        memory_hygiene_enabled=True,
        memory_hygiene_interval_hours=24,
        memory_hygiene_only_if_active=False,
        memory_hygiene_prompt=None,
        memory_hygiene_target_hour=None,
        memory_hygiene_extra_instructions=None,
        next_hygiene_run_at=None,
        last_hygiene_run_at=None,
    )
    return Bot(**{**defaults, **overrides})
