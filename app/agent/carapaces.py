"""Carapace registry — composable skill+tool bundles.

Carapaces are loaded from the DB at startup and resolved into existing
primitives (skills, tools, pinned tools, system prompt fragments) at
context assembly time.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy import select

from app.agent.bots import SkillConfig, _parse_skill_entry
from app.db.engine import async_session
from app.db.models import Carapace as CarapaceRow

logger = logging.getLogger(__name__)

# In-memory registry: carapace_id → CarapaceRow-like dict
_registry: dict[str, dict] = {}

CARAPACES_DIR = Path("carapaces")


@dataclass
class ResolvedCarapace:
    """Flattened result of resolving one or more carapaces."""
    skills: list[SkillConfig] = field(default_factory=list)
    local_tools: list[str] = field(default_factory=list)
    mcp_tools: list[str] = field(default_factory=list)
    pinned_tools: list[str] = field(default_factory=list)
    system_prompt_fragments: list[str] = field(default_factory=list)


def _carapace_to_dict(row: CarapaceRow) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "skills": row.skills or [],
        "local_tools": row.local_tools or [],
        "mcp_tools": row.mcp_tools or [],
        "pinned_tools": row.pinned_tools or [],
        "system_prompt_fragment": row.system_prompt_fragment,
        "includes": row.includes or [],
        "tags": row.tags or [],
        "source_path": row.source_path,
        "source_type": row.source_type,
        "content_hash": row.content_hash,
    }


def get_carapace(carapace_id: str) -> dict | None:
    """Get a carapace from the in-memory registry."""
    return _registry.get(carapace_id)


def list_carapaces() -> list[dict]:
    """List all carapaces from the in-memory registry."""
    return list(_registry.values())


def resolve_carapaces(ids: list[str], *, max_depth: int = 5) -> ResolvedCarapace:
    """Resolve carapace IDs into a flattened ResolvedCarapace.

    Handles recursive includes with cycle detection.
    """
    result = ResolvedCarapace()
    _seen_skills: set[str] = set()
    _seen_tools: set[str] = set()
    _seen_mcp: set[str] = set()
    _seen_pinned: set[str] = set()
    _seen_fragments: set[str] = set()  # track carapace IDs whose fragment was added

    def _resolve(cid: str, visited: set[str], depth: int) -> None:
        if cid in visited:
            logger.warning("Carapace cycle detected: %s (visited: %s)", cid, visited)
            return
        if depth > max_depth:
            logger.warning("Carapace max depth %d exceeded at %s", max_depth, cid)
            return
        c = _registry.get(cid)
        if c is None:
            logger.warning("Carapace '%s' not found in registry", cid)
            return

        visited = visited | {cid}

        # Resolve includes first (depth-first)
        for inc_id in c.get("includes", []):
            _resolve(inc_id, visited, depth + 1)

        # Merge skills (deduplicate by id)
        for entry in c.get("skills", []):
            sc = _parse_skill_entry(entry)
            if sc.id not in _seen_skills:
                _seen_skills.add(sc.id)
                result.skills.append(sc)

        # Merge tools (deduplicate)
        for t in c.get("local_tools", []):
            if t not in _seen_tools:
                _seen_tools.add(t)
                result.local_tools.append(t)

        for t in c.get("mcp_tools", []):
            if t not in _seen_mcp:
                _seen_mcp.add(t)
                result.mcp_tools.append(t)

        for t in c.get("pinned_tools", []):
            if t not in _seen_pinned:
                _seen_pinned.add(t)
                result.pinned_tools.append(t)

        # Append system prompt fragment (order matters: includes first, then self)
        frag = c.get("system_prompt_fragment")
        if frag and frag.strip() and cid not in _seen_fragments:
            _seen_fragments.add(cid)
            result.system_prompt_fragments.append(frag.strip())

    for cid in ids:
        _resolve(cid, set(), 0)

    return result


async def load_carapaces() -> None:
    """Load all carapaces from DB into the in-memory registry."""
    _registry.clear()
    async with async_session() as db:
        rows = (await db.execute(select(CarapaceRow))).scalars().all()
    for row in rows:
        _registry[row.id] = _carapace_to_dict(row)
    logger.info("Loaded %d carapace(s) from DB", len(_registry))


async def reload_carapaces() -> None:
    """Re-populate registry from DB — called after admin edits."""
    await load_carapaces()


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _integration_dirs() -> list[Path]:
    """Return all integration/package directories."""
    dirs = [Path("integrations"), Path("packages")]
    try:
        from app.config import settings
        extra = settings.INTEGRATION_DIRS
    except Exception:
        extra = ""
    if extra:
        for p in extra.split(":"):
            p = p.strip()
            if p:
                path = Path(p).expanduser().resolve()
                if path.is_dir():
                    dirs.append(path)
    return dirs


def collect_carapace_files() -> list[tuple[Path, str, str]]:
    """Return (path, carapace_id, source_type) for all discoverable carapace YAML files."""
    items: list[tuple[Path, str, str]] = []

    # carapaces/*.yaml (global, flat files)
    if CARAPACES_DIR.is_dir():
        for p in sorted(CARAPACES_DIR.glob("*.yaml")):
            items.append((p, p.stem, "file"))

    # carapaces/*/carapace.yaml (subdirectory carapaces)
    if CARAPACES_DIR.is_dir():
        for sub_dir in sorted(CARAPACES_DIR.iterdir()):
            if not sub_dir.is_dir():
                continue
            carapace_yaml = sub_dir / "carapace.yaml"
            if carapace_yaml.is_file():
                items.append((carapace_yaml, sub_dir.name, "file"))

    # integrations/*/carapaces/*.yaml
    for base_dir in _integration_dirs():
        if not base_dir.is_dir():
            continue
        for intg_dir in sorted(base_dir.iterdir()):
            if not intg_dir.is_dir():
                continue
            intg_carapaces = intg_dir / "carapaces"
            if intg_carapaces.is_dir():
                for p in sorted(intg_carapaces.glob("*.yaml")):
                    carapace_id = f"{base_dir.name}/{intg_dir.name}/{p.stem}"
                    items.append((p, carapace_id, "integration"))

    # integrations/*/carapaces/*/carapace.yaml (subdirectory integration carapaces)
    for base_dir in _integration_dirs():
        if not base_dir.is_dir():
            continue
        for intg_dir in sorted(base_dir.iterdir()):
            if not intg_dir.is_dir():
                continue
            intg_carapaces = intg_dir / "carapaces"
            if intg_carapaces.is_dir():
                for sub_dir in sorted(intg_carapaces.iterdir()):
                    if not sub_dir.is_dir():
                        continue
                    carapace_yaml = sub_dir / "carapace.yaml"
                    if carapace_yaml.is_file():
                        carapace_id = f"{base_dir.name}/{intg_dir.name}/{sub_dir.name}"
                        items.append((carapace_yaml, carapace_id, "integration"))

    return items


async def seed_carapaces_from_yaml() -> None:
    """Seed carapaces from YAML files into DB.

    - New carapaces are inserted.
    - Existing file-managed carapaces are updated if content_hash changed.
    - Manual (admin-created) carapaces are never overwritten.
    """
    yaml_files = collect_carapace_files()
    if not yaml_files:
        return

    seeded = 0
    updated = 0
    async with async_session() as db:
        for path, carapace_id, source_type in yaml_files:
            try:
                raw = path.read_text(encoding="utf-8")
            except Exception:
                logger.exception("Cannot read carapace file %s", path)
                continue

            data = yaml.safe_load(raw)
            if not data:
                continue

            # Use id from file content if present, otherwise use filename-derived id
            cid = data.get("id", carapace_id)
            content_hash = _sha256(raw)
            now = datetime.now(timezone.utc)

            existing = await db.get(CarapaceRow, cid)
            if existing is None:
                row = CarapaceRow(
                    id=cid,
                    name=data.get("name", cid),
                    description=data.get("description"),
                    skills=data.get("skills", []),
                    local_tools=data.get("local_tools", []),
                    mcp_tools=data.get("mcp_tools", []),
                    pinned_tools=data.get("pinned_tools", []),
                    system_prompt_fragment=data.get("system_prompt_fragment"),
                    includes=data.get("includes", []),
                    tags=data.get("tags", []),
                    source_path=str(path.resolve()),
                    source_type=source_type,
                    content_hash=content_hash,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
                seeded += 1
            elif (
                existing.source_type in ("file", "integration")
                and existing.content_hash != content_hash
            ):
                existing.name = data.get("name", cid)
                existing.description = data.get("description")
                existing.skills = data.get("skills", [])
                existing.local_tools = data.get("local_tools", [])
                existing.mcp_tools = data.get("mcp_tools", [])
                existing.pinned_tools = data.get("pinned_tools", [])
                existing.system_prompt_fragment = data.get("system_prompt_fragment")
                existing.includes = data.get("includes", [])
                existing.tags = data.get("tags", [])
                existing.source_path = str(path.resolve())
                existing.source_type = source_type
                existing.content_hash = content_hash
                existing.updated_at = now
                updated += 1

        await db.commit()
    logger.info("Synced carapaces from YAML: %d seeded, %d updated", seeded, updated)
