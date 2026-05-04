"""Lint-style guard for skill frontmatter quality.

Skills are surfaced via their `description:` field in skill indexes injected
into prompts. Long descriptions waste prompt budget on every turn — push the
detail into the body where bots fetch it on demand via `get_skill`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "skills"
DESCRIPTION_CAP = 280


def _iter_skill_files() -> list[Path]:
    if not SKILLS_ROOT.exists():
        return []
    return sorted(SKILLS_ROOT.rglob("*.md"))


def _parse_frontmatter(text: str) -> dict | None:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return None
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except Exception:
        return {}
    return meta if isinstance(meta, dict) else {}


def test_skill_descriptions_within_cap():
    """Skill `description:` must stay <= DESCRIPTION_CAP chars.

    Matches the contract documented in docs/plans/bot-readable-docs.md:
    long reference manuals demote into docs/reference/; the residual skill
    keeps a short procedural description.
    """
    offenders: list[tuple[Path, int]] = []
    for path in _iter_skill_files():
        meta = _parse_frontmatter(path.read_text(encoding="utf-8"))
        if not meta:
            continue
        desc = meta.get("description")
        if not isinstance(desc, str):
            continue
        desc_trimmed = desc.strip()
        if len(desc_trimmed) > DESCRIPTION_CAP:
            offenders.append((path.relative_to(REPO_ROOT), len(desc_trimmed)))

    if offenders:
        formatted = "\n".join(f"  {p} ({n} chars)" for p, n in offenders)
        pytest.fail(
            f"Skill descriptions exceed {DESCRIPTION_CAP} char cap:\n{formatted}\n"
            "Trim the description to a 1-2 line trigger summary; push detail to the body."
        )
