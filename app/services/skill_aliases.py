"""Skill ID aliasing.

When a skill moves between filesystem locations or clusters, persisted
references (bot enrollments, run preset prompts, slash command payloads,
external integrations) keep the old ID. The skill resolver checks this map so
old IDs continue to load the new content.

Aliases are runtime-only; the canonical ID (the value) is what `seed_skills`
and `_walk_skill_files` produce. Old IDs (the keys) do **not** correspond to
any file on disk after the move.
"""
from __future__ import annotations


# Old skill ID -> new canonical skill ID.
# Added 2026-05-02 with the skills/workspace/project_* -> skills/project/*
# move (Phase 4AY-a of the Project Factory cohesion pass). Kept indefinitely
# until dogfood data has fully migrated.
LEGACY_SKILL_ID_ALIASES: dict[str, str] = {
    "workspace/project_lifecycle": "project",
    "workspace/project_init": "project/setup/init",
    "workspace/project_prd": "project/plan/prd",
    "workspace/project_stories": "project/plan/run_packs",
    "workspace/project_coding_runs": "project/runs/implement",
    "workspace/issue_intake": "project/intake",
}


def resolve_skill_id(skill_id: str) -> str:
    """Return the canonical skill ID for ``skill_id``.

    If ``skill_id`` is a known legacy alias, return the new ID. Otherwise
    return the input unchanged.
    """
    return LEGACY_SKILL_ID_ALIASES.get(skill_id, skill_id)


def is_legacy_alias(skill_id: str) -> bool:
    """Return True if ``skill_id`` is a known legacy alias."""
    return skill_id in LEGACY_SKILL_ID_ALIASES
