"""Factories for Skill and BotSkillEnrollment."""
from __future__ import annotations

import uuid

from app.db.models import BotSkillEnrollment, Skill


def build_skill(**overrides) -> Skill:
    suffix = uuid.uuid4().hex[:8]
    defaults = dict(
        id=f"skills/{suffix}",
        name=f"Test Skill {suffix}",
        description="Test skill.",
        triggers=[],
        scripts=[],
        content="Test skill content.",
        content_hash=f"hash-{suffix}",
    )
    return Skill(**{**defaults, **overrides})


def build_bot_skill_enrollment(**overrides) -> BotSkillEnrollment:
    suffix = uuid.uuid4().hex[:8]
    defaults = dict(
        bot_id=f"bot-{suffix}",
        skill_id=f"skills/{suffix}",
        source="manual",
    )
    return BotSkillEnrollment(**{**defaults, **overrides})
