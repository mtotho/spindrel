"""File-based sync service for skills and knowledge.

Scans structured directories on startup and via a watchfiles watcher.
Hash-based change detection; auto-deletes orphaned DB rows.

Supported directories:
  skills/*.md                        → skills (source_type='file', global)
  bots/{id}/skills/*.md              → skills (source_type='file', name='bots/{id}/{stem}')
  knowledge/*.md                     → bot_knowledge (bot_id=NULL, source_type='file')
  bots/{id}/knowledge/*.md           → bot_knowledge (bot_id=id, source_type='file')
  integrations/{id}/skills/*.md      → skills (source_type='integration')
  integrations/{id}/knowledge/*.md   → bot_knowledge (bot_id=NULL, source_type='integration')
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.embeddings import embed_text as _embed_text, embed_batch as _embed_batch
from app.config import settings
from app.db.engine import async_session
from app.db.models import BotKnowledge, PromptTemplate, Skill as SkillRow

logger = logging.getLogger(__name__)

# Source type constants
SOURCE_FILE = "file"
SOURCE_INTEGRATION = "integration"
SOURCE_MANUAL = "manual"
SOURCE_TOOL = "tool"


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return {}, content
    import yaml
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except Exception:
        meta = {}
    return meta, content[match.end():]


def _chunk_markdown(body: str, skill_name: str, max_chunk: int = 1500) -> list[str]:
    from app.agent.skills import _chunk_markdown as _chunk
    return _chunk(body, skill_name, max_chunk)


async def _embed_skill_from_content(skill_id: str, content: str, content_hash: str) -> None:
    """Re-embed a skill row using the shared skill embedding logic."""
    from app.agent.skills import _embed_skill_row
    await _embed_skill_row(skill_id, content, content_hash)


async def _embed_knowledge_row(row: BotKnowledge) -> None:
    """Compute embedding for a knowledge row and update it."""
    try:
        emb = await _embed_text(row.content)
        async with async_session() as db:
            r = await db.get(BotKnowledge, row.id)
            if r:
                r.embedding = emb
                r.updated_at = datetime.now(timezone.utc)
                await db.commit()
    except Exception:
        logger.exception("Failed to embed knowledge row '%s'", row.name)


def _integration_dirs() -> list[Path]:
    """Return all integration directories (in-repo + INTEGRATION_DIRS)."""
    dirs = [Path("integrations")]
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


def _collect_skill_files() -> list[tuple[Path, str, str]]:
    """Return (path, skill_id, source_type) for all discoverable skill .md files.

    source_type is 'file' or 'integration'.
    skill_id is the logical key (used as DB primary key).
    """
    items: list[tuple[Path, str, str]] = []

    # skills/*.md (global)
    skills_dir = Path("skills")
    if skills_dir.is_dir():
        for p in sorted(skills_dir.glob("*.md")):
            items.append((p, p.stem, SOURCE_FILE))

    # bots/{id}/skills/*.md
    bots_dir = Path("bots")
    if bots_dir.is_dir():
        for bot_dir in sorted(bots_dir.iterdir()):
            if not bot_dir.is_dir():
                continue
            bot_skills = bot_dir / "skills"
            if bot_skills.is_dir():
                for p in sorted(bot_skills.glob("*.md")):
                    skill_id = f"bots/{bot_dir.name}/{p.stem}"
                    items.append((p, skill_id, SOURCE_FILE))

    # integrations/*/skills/*.md (in-repo + external)
    for integrations_dir in _integration_dirs():
        if not integrations_dir.is_dir():
            continue
        for intg_dir in sorted(integrations_dir.iterdir()):
            if not intg_dir.is_dir():
                continue
            intg_skills = intg_dir / "skills"
            if intg_skills.is_dir():
                for p in sorted(intg_skills.glob("*.md")):
                    skill_id = f"integrations/{intg_dir.name}/{p.stem}"
                    items.append((p, skill_id, SOURCE_INTEGRATION))

    return items


def _collect_knowledge_files() -> list[tuple[Path, str, str | None, str]]:
    """Return (path, name, bot_id_or_none, source_type) for all discoverable knowledge .md files."""
    items: list[tuple[Path, str, str | None, str]] = []

    # knowledge/*.md (global, cross-bot)
    knowledge_dir = Path("knowledge")
    if knowledge_dir.is_dir():
        for p in sorted(knowledge_dir.glob("*.md")):
            items.append((p, p.stem, None, SOURCE_FILE))

    # bots/{id}/knowledge/*.md
    bots_dir = Path("bots")
    if bots_dir.is_dir():
        for bot_dir in sorted(bots_dir.iterdir()):
            if not bot_dir.is_dir():
                continue
            bot_knowledge = bot_dir / "knowledge"
            if bot_knowledge.is_dir():
                for p in sorted(bot_knowledge.glob("*.md")):
                    items.append((p, p.stem, bot_dir.name, SOURCE_FILE))

    # integrations/*/knowledge/*.md (in-repo + external)
    for integrations_dir in _integration_dirs():
        if not integrations_dir.is_dir():
            continue
        for intg_dir in sorted(integrations_dir.iterdir()):
            if not intg_dir.is_dir():
                continue
            intg_knowledge = intg_dir / "knowledge"
            if intg_knowledge.is_dir():
                for p in sorted(intg_knowledge.glob("*.md")):
                    items.append((p, p.stem, None, SOURCE_INTEGRATION))

    return items


def _collect_prompt_template_files() -> list[tuple[Path, str, str]]:
    """Return (path, name, source_type) for all discoverable prompt template .md files.

    Scans prompts/*.md (global templates).
    """
    items: list[tuple[Path, str, str]] = []
    prompts_dir = Path("prompts")
    if prompts_dir.is_dir():
        for p in sorted(prompts_dir.glob("*.md")):
            items.append((p, p.stem, SOURCE_FILE))
    return items


async def sync_all_files(db: AsyncSession | None = None) -> dict[str, Any]:
    """Scan all file-drop directories, upsert changed rows, delete orphaned rows.

    Returns a dict with counts and diagnostic details.
    """
    counts: dict[str, Any] = {"added": 0, "updated": 0, "deleted": 0, "unchanged": 0, "errors": []}

    # --- Skills ---
    skill_files = _collect_skill_files()
    seen_skill_ids: set[str] = set()

    cwd = str(Path.cwd().resolve())
    skills_dir = Path("skills")
    skills_dir_resolved = str(skills_dir.resolve()) if skills_dir.exists() else None
    skills_dir_exists = skills_dir.is_dir()
    logger.info(
        "file_sync: cwd=%s, skills_dir exists=%s, resolved=%s, found %d skill files on disk: %s",
        cwd, skills_dir_exists, skills_dir_resolved, len(skill_files),
        [f"{sid} ({p})" for p, sid, _ in skill_files],
    )
    counts["_diagnostics"] = {
        "cwd": cwd,
        "skills_dir_resolved": skills_dir_resolved,
        "skills_dir_exists": skills_dir_exists,
        "files_on_disk": [{"id": sid, "path": str(p), "source_type": st} for p, sid, st in skill_files],
    }

    for path, skill_id, source_type in skill_files:
        seen_skill_ids.add(skill_id)
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            logger.exception("Cannot read skill file %s", path)
            counts["errors"].append(f"Cannot read {path}")
            continue

        content_hash = _sha256(raw)
        meta, _ = _parse_frontmatter(raw)
        display_name = meta.get("name", skill_id.replace("_", " ").replace("/", " / ").title())
        source_path = str(path.resolve())

        try:
            async with async_session() as session:
                existing = await session.get(SkillRow, skill_id)
                if existing is None:
                    row = SkillRow(
                        id=skill_id,
                        name=display_name,
                        content=raw,
                        content_hash=content_hash,
                        source_path=source_path,
                        source_type=source_type,
                        updated_at=datetime.now(timezone.utc),
                    )
                    session.add(row)
                    await session.commit()
                    counts["added"] += 1
                    logger.info("file_sync: added skill '%s' from %s", skill_id, path)
                    await _embed_skill_from_content(skill_id, raw, content_hash)
                elif existing.content_hash != content_hash:
                    existing.name = display_name
                    existing.content = raw
                    existing.content_hash = content_hash
                    existing.source_path = source_path
                    existing.source_type = source_type
                    existing.updated_at = datetime.now(timezone.utc)
                    await session.commit()
                    counts["updated"] += 1
                    logger.info("file_sync: updated skill '%s' from %s", skill_id, path)
                    await _embed_skill_from_content(skill_id, raw, content_hash)
                else:
                    counts["unchanged"] += 1
                    # Ensure source metadata is up to date even if content unchanged
                    if existing.source_type != source_type or existing.source_path != source_path:
                        existing.source_type = source_type
                        existing.source_path = source_path
                        await session.commit()
        except Exception:
            logger.exception("file_sync: DB error syncing skill '%s'", skill_id)
            counts["errors"].append(f"DB error for skill '{skill_id}'")

    # Delete orphaned file/integration skills no longer on disk
    # Safety: skip orphan deletion if we found zero files — likely a mount/CWD issue
    if skill_files:
        async with async_session() as session:
            stmt = select(SkillRow).where(
                SkillRow.source_type.in_([SOURCE_FILE, SOURCE_INTEGRATION])
            )
            all_file_skills = list((await session.execute(stmt)).scalars().all())
            for row in all_file_skills:
                if row.id not in seen_skill_ids:
                    await session.delete(row)
                    counts["deleted"] += 1
                    logger.info("file_sync: deleted orphaned skill '%s'", row.id)
            await session.commit()
    elif not skill_files:
        # Log a warning — zero files found might mean a mount issue
        async with async_session() as session:
            existing_count = (await session.execute(
                select(func.count()).select_from(SkillRow).where(
                    SkillRow.source_type.in_([SOURCE_FILE, SOURCE_INTEGRATION])
                )
            )).scalar_one()
        if existing_count > 0:
            logger.warning(
                "file_sync: found 0 skill files on disk but %d file-sourced skills in DB. "
                "Skipping orphan deletion — possible volume mount issue. cwd=%s",
                existing_count, cwd,
            )
            counts["errors"].append(
                f"Found 0 files on disk but {existing_count} file-sourced skills in DB — "
                f"skipping orphan deletion (possible mount issue, cwd={cwd})"
            )

    # --- Knowledge ---
    knowledge_files = _collect_knowledge_files()
    seen_knowledge_paths: set[str] = set()

    for path, name, bot_id, source_type in knowledge_files:
        source_path = str(path.resolve())
        seen_knowledge_paths.add(source_path)
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            logger.exception("Cannot read knowledge file %s", path)
            continue

        content_hash = _sha256(raw)

        async with async_session() as session:
            stmt = select(BotKnowledge).where(
                BotKnowledge.source_path == source_path,
                BotKnowledge.source_type.in_([SOURCE_FILE, SOURCE_INTEGRATION]),
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()

            if existing is None:
                # Create new row (no session_id, no client_id — global)
                row = BotKnowledge(
                    name=name,
                    content=raw,
                    bot_id=bot_id,
                    client_id=None,
                    session_id=None,
                    created_by_bot="file_sync",
                    source_path=source_path,
                    source_type=source_type,
                    editable_from_tool=False,
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(row)
                await session.flush()
                try:
                    row.embedding = await _embed_text(raw)
                except Exception:
                    logger.exception("Failed to embed knowledge '%s'", name)
                await session.commit()
                counts["added"] += 1
                logger.info("file_sync: added knowledge '%s' from %s", name, path)
            elif existing.content != raw:
                existing.content = raw
                existing.name = name
                existing.bot_id = bot_id
                existing.source_type = source_type
                existing.editable_from_tool = False
                existing.updated_at = datetime.now(timezone.utc)
                try:
                    existing.embedding = await _embed_text(raw)
                except Exception:
                    logger.exception("Failed to re-embed knowledge '%s'", name)
                await session.commit()
                counts["updated"] += 1
                logger.info("file_sync: updated knowledge '%s' from %s", name, path)

    # Delete orphaned file/integration knowledge rows
    async with async_session() as session:
        stmt = select(BotKnowledge).where(
            BotKnowledge.source_type.in_([SOURCE_FILE, SOURCE_INTEGRATION])
        )
        all_file_knowledge = list((await session.execute(stmt)).scalars().all())
        for row in all_file_knowledge:
            if row.source_path not in seen_knowledge_paths:
                await session.delete(row)
                counts["deleted"] += 1
                logger.info("file_sync: deleted orphaned knowledge '%s'", row.name)
        await session.commit()

    # --- Prompt Templates ---
    template_files = _collect_prompt_template_files()
    seen_template_paths: set[str] = set()

    for path, name, source_type in template_files:
        source_path = str(path.resolve())
        seen_template_paths.add(source_path)
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            logger.exception("Cannot read prompt template file %s", path)
            continue

        content_hash = _sha256(raw)
        meta, body = _parse_frontmatter(raw)
        display_name = meta.get("name", name.replace("_", " ").replace("-", " ").title())
        category = meta.get("category")
        description = meta.get("description")
        tags = meta.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        async with async_session() as session:
            stmt = select(PromptTemplate).where(
                PromptTemplate.source_path == source_path,
                PromptTemplate.source_type == SOURCE_FILE,
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()

            if existing is None:
                row = PromptTemplate(
                    name=display_name,
                    description=description,
                    content=raw,
                    category=category,
                    tags=tags if tags else [],
                    source_type=source_type,
                    source_path=source_path,
                    content_hash=content_hash,
                )
                session.add(row)
                await session.commit()
                counts["added"] += 1
                logger.info("file_sync: added prompt template '%s' from %s", display_name, path)
            elif existing.content_hash != content_hash:
                existing.name = display_name
                existing.description = description
                existing.content = raw
                existing.category = category
                existing.tags = tags if tags else []
                existing.content_hash = content_hash
                existing.source_path = source_path
                existing.updated_at = datetime.now(timezone.utc)
                await session.commit()
                counts["updated"] += 1
                logger.info("file_sync: updated prompt template '%s' from %s", display_name, path)

    # Delete orphaned file-managed prompt templates
    async with async_session() as session:
        stmt = select(PromptTemplate).where(
            PromptTemplate.source_type == SOURCE_FILE
        )
        all_file_templates = list((await session.execute(stmt)).scalars().all())
        for row in all_file_templates:
            if row.source_path not in seen_template_paths:
                await session.delete(row)
                counts["deleted"] += 1
                logger.info("file_sync: deleted orphaned prompt template '%s'", row.name)
        await session.commit()

    logger.info(
        "file_sync complete: +%d added, ~%d updated, =%d unchanged, -%d deleted, %d errors",
        counts["added"], counts["updated"], counts["unchanged"],
        counts["deleted"], len(counts["errors"]),
    )
    if counts["errors"]:
        logger.warning("file_sync errors: %s", counts["errors"])
    return counts


async def sync_changed_file(path: Path) -> None:
    """Handle a single file change event from the watcher."""
    path = path.resolve()
    path_str = str(path)

    if not path.exists():
        # File deleted — remove DB rows referencing it
        async with async_session() as session:
            # Skill
            stmt = select(SkillRow).where(SkillRow.source_path == path_str)
            rows = list((await session.execute(stmt)).scalars().all())
            for row in rows:
                await session.delete(row)
            # Knowledge
            stmt2 = select(BotKnowledge).where(BotKnowledge.source_path == path_str)
            rows2 = list((await session.execute(stmt2)).scalars().all())
            for row in rows2:
                await session.delete(row)
            # Prompt templates
            stmt3 = select(PromptTemplate).where(PromptTemplate.source_path == path_str)
            rows3 = list((await session.execute(stmt3)).scalars().all())
            for row in rows3:
                await session.delete(row)
            if rows or rows2 or rows3:
                await session.commit()
                logger.info("file_sync: removed DB rows for deleted file %s", path)
        return

    if path.suffix != ".md":
        return

    raw = path.read_text(encoding="utf-8")
    content_hash = _sha256(raw)

    # Determine what kind of file this is by checking its location
    rel_parts = _classify_path(path)
    if rel_parts is None:
        return

    kind, skill_id_or_name, bot_id, source_type = rel_parts

    if kind == "skill":
        skill_id = skill_id_or_name
        meta, _ = _parse_frontmatter(raw)
        display_name = meta.get("name", skill_id.replace("_", " ").title())
        async with async_session() as session:
            existing = await session.get(SkillRow, skill_id)
            if existing is None:
                row = SkillRow(
                    id=skill_id,
                    name=display_name,
                    content=raw,
                    content_hash=content_hash,
                    source_path=path_str,
                    source_type=source_type,
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(row)
                await session.commit()
                logger.info("file_sync(watch): added skill '%s'", skill_id)
                await _embed_skill_from_content(skill_id, raw, content_hash)
            elif existing.content_hash != content_hash:
                existing.name = display_name
                existing.content = raw
                existing.content_hash = content_hash
                existing.source_path = path_str
                existing.source_type = source_type
                existing.updated_at = datetime.now(timezone.utc)
                await session.commit()
                logger.info("file_sync(watch): updated skill '%s'", skill_id)
                await _embed_skill_from_content(skill_id, raw, content_hash)
    elif kind == "knowledge":
        name = skill_id_or_name
        async with async_session() as session:
            stmt = select(BotKnowledge).where(
                BotKnowledge.source_path == path_str,
                BotKnowledge.source_type.in_([SOURCE_FILE, SOURCE_INTEGRATION]),
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is None:
                row = BotKnowledge(
                    name=name,
                    content=raw,
                    bot_id=bot_id,
                    client_id=None,
                    session_id=None,
                    created_by_bot="file_sync",
                    source_path=path_str,
                    source_type=source_type,
                    editable_from_tool=False,
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(row)
                await session.flush()
                try:
                    row.embedding = await _embed_text(raw)
                except Exception:
                    logger.exception("Failed to embed knowledge '%s'", name)
                await session.commit()
                logger.info("file_sync(watch): added knowledge '%s'", name)
            elif existing.content != raw:
                existing.content = raw
                existing.updated_at = datetime.now(timezone.utc)
                try:
                    existing.embedding = await _embed_text(raw)
                except Exception:
                    logger.exception("Failed to re-embed knowledge '%s'", name)
                await session.commit()
                logger.info("file_sync(watch): updated knowledge '%s'", name)
    elif kind == "prompt_template":
        name = skill_id_or_name
        meta, _ = _parse_frontmatter(raw)
        display_name = meta.get("name", name.replace("_", " ").replace("-", " ").title())
        category = meta.get("category")
        description = meta.get("description")
        tags = meta.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        async with async_session() as session:
            stmt = select(PromptTemplate).where(
                PromptTemplate.source_path == path_str,
                PromptTemplate.source_type == SOURCE_FILE,
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is None:
                row = PromptTemplate(
                    name=display_name,
                    description=description,
                    content=raw,
                    category=category,
                    tags=tags if tags else [],
                    source_type=source_type,
                    source_path=path_str,
                    content_hash=content_hash,
                )
                session.add(row)
                await session.commit()
                logger.info("file_sync(watch): added prompt template '%s'", display_name)
            elif existing.content_hash != content_hash:
                existing.name = display_name
                existing.description = description
                existing.content = raw
                existing.category = category
                existing.tags = tags if tags else []
                existing.content_hash = content_hash
                existing.updated_at = datetime.now(timezone.utc)
                await session.commit()
                logger.info("file_sync(watch): updated prompt template '%s'", display_name)


def _classify_path(path: Path) -> tuple[str, str, str | None, str] | None:
    """Return (kind, id/name, bot_id_or_none, source_type) or None if not a managed path."""
    path = path.resolve()
    try:
        rel = path.relative_to(Path.cwd().resolve())
    except ValueError:
        return None

    parts = rel.parts
    if not parts:
        return None

    # skills/*.md
    if len(parts) == 2 and parts[0] == "skills" and parts[1].endswith(".md"):
        return ("skill", Path(parts[1]).stem, None, SOURCE_FILE)

    # bots/{id}/skills/*.md
    if len(parts) == 4 and parts[0] == "bots" and parts[2] == "skills" and parts[3].endswith(".md"):
        skill_id = f"bots/{parts[1]}/{Path(parts[3]).stem}"
        return ("skill", skill_id, None, SOURCE_FILE)

    # integrations/{id}/skills/*.md
    if len(parts) == 4 and parts[0] == "integrations" and parts[2] == "skills" and parts[3].endswith(".md"):
        skill_id = f"integrations/{parts[1]}/{Path(parts[3]).stem}"
        return ("skill", skill_id, None, SOURCE_INTEGRATION)

    # knowledge/*.md
    if len(parts) == 2 and parts[0] == "knowledge" and parts[1].endswith(".md"):
        return ("knowledge", Path(parts[1]).stem, None, SOURCE_FILE)

    # bots/{id}/knowledge/*.md
    if len(parts) == 4 and parts[0] == "bots" and parts[2] == "knowledge" and parts[3].endswith(".md"):
        return ("knowledge", Path(parts[3]).stem, parts[1], SOURCE_FILE)

    # integrations/{id}/knowledge/*.md
    if len(parts) == 4 and parts[0] == "integrations" and parts[2] == "knowledge" and parts[3].endswith(".md"):
        return ("knowledge", Path(parts[3]).stem, None, SOURCE_INTEGRATION)

    # prompts/*.md
    if len(parts) == 2 and parts[0] == "prompts" and parts[1].endswith(".md"):
        return ("prompt_template", Path(parts[1]).stem, None, SOURCE_FILE)

    return None


async def watch_files() -> None:
    """Background watcher — monitors all file-drop directories for .md changes.

    Auto-restarts on crash with exponential backoff (max 60s).
    """
    try:
        from watchfiles import awatch, Change
    except ImportError:
        logger.warning("watchfiles not installed; file watching disabled")
        return

    backoff = 1.0
    while True:
        watch_dirs: list[str] = []
        for d in ["skills", "knowledge", "bots", "integrations", "prompts"]:
            p = Path(d)
            if p.exists():
                watch_dirs.append(str(p))

        if not watch_dirs:
            logger.info("file_sync watcher: no directories to watch")
            return

        logger.info("file_sync watcher: watching %s", watch_dirs)

        try:
            async for changes in awatch(*watch_dirs):
                backoff = 1.0  # reset backoff on successful event
                for change_type, changed_path in changes:
                    p = Path(changed_path)
                    if p.suffix != ".md":
                        continue
                    try:
                        await sync_changed_file(p)
                    except Exception:
                        logger.exception("file_sync watcher error handling %s", changed_path)
        except asyncio.CancelledError:
            logger.info("file_sync watcher cancelled")
            return
        except Exception:
            logger.exception("file_sync watcher crashed, restarting in %.0fs", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
