"""Factory for bot-authored Skill rows (``id = bots/{bot_id}/{slug}``).

Separate from ``tests/factories/skills.py::build_skill`` (which defaults
``id = skills/{uuid}`` for classic skills). Bot-authored skills are written by
the ``manage_bot_skill`` tool and share the ``skills`` table but follow the
``bots/{bot_id}/{slug}`` ID convention with ``source_type='tool'``.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from app.db.models import Skill

_SLUG_RE = re.compile(r"[^a-z0-9-]")


def _slugify(name: str) -> str:
    slug = name.strip().lower().replace(" ", "-")
    slug = _SLUG_RE.sub("", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def build_bot_skill(bot_id: str, name: str = "my-skill", **overrides) -> Skill:
    """Build a bot-authored Skill row.

    ``id`` defaults to ``bots/{bot_id}/{slug(name)}``. Pass ``id`` override
    to short-circuit the slug composition.
    """
    slug = _slugify(name)
    content = overrides.pop("content", f"# {name}\n\n" + "body " * 20)
    defaults = dict(
        id=f"bots/{bot_id}/{slug}",
        name=name,
        description=content[:200].strip(),
        category=None,
        triggers=[],
        content=content,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        source_path=None,
        source_type="tool",
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
        last_surfaced_at=None,
        surface_count=0,
        archived_at=None,
    )
    return Skill(**{**defaults, **overrides})
