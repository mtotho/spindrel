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
  prompts/**/*.md                    → prompt_templates (source_type='file')
  integrations/{id}/prompts/**/*.md  → prompt_templates (source_type='integration')
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
from app.db.models import BotKnowledge, Carapace as CarapaceRow, PromptTemplate, Skill as SkillRow

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
    """Return all integration/package directories (in-repo + INTEGRATION_DIRS)."""
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

    # integrations/*/skills/*.md and packages/*/skills/*.md (in-repo + external)
    for base_dir in _integration_dirs():
        if not base_dir.is_dir():
            continue
        prefix = base_dir.name  # "integrations", "packages", or external dir name
        for intg_dir in sorted(base_dir.iterdir()):
            if not intg_dir.is_dir():
                continue
            intg_skills = intg_dir / "skills"
            if intg_skills.is_dir():
                for p in sorted(intg_skills.glob("*.md")):
                    skill_id = f"{prefix}/{intg_dir.name}/{p.stem}"
                    items.append((p, skill_id, SOURCE_INTEGRATION))

    # carapaces/*/skills/*.md (carapace-scoped skills)
    carapaces_dir = Path("carapaces")
    if carapaces_dir.is_dir():
        for c_dir in sorted(carapaces_dir.iterdir()):
            if not c_dir.is_dir():
                continue
            c_skills = c_dir / "skills"
            if c_skills.is_dir():
                for p in sorted(c_skills.glob("*.md")):
                    skill_id = f"carapaces/{c_dir.name}/{p.stem}"
                    items.append((p, skill_id, SOURCE_FILE))

    # integrations/*/carapaces/*/skills/*.md (integration carapace-scoped skills)
    for base_dir in _integration_dirs():
        if not base_dir.is_dir():
            continue
        for intg_dir in sorted(base_dir.iterdir()):
            if not intg_dir.is_dir():
                continue
            intg_carapaces = intg_dir / "carapaces"
            if not intg_carapaces.is_dir():
                continue
            for c_dir in sorted(intg_carapaces.iterdir()):
                if not c_dir.is_dir():
                    continue
                c_skills = c_dir / "skills"
                if c_skills.is_dir():
                    for p in sorted(c_skills.glob("*.md")):
                        skill_id = f"{base_dir.name}/{intg_dir.name}/carapaces/{c_dir.name}/{p.stem}"
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

    Scans prompts/**/*.md (global, recursive) and integrations/*/prompts/**/*.md
    (integration-shipped, recursive).  Subdirectories are supported for organizational
    grouping — the template name is always the file stem (not the path).
    """
    items: list[tuple[Path, str, str]] = []
    # prompts/**/*.md (global, recursive)
    prompts_dir = Path("prompts")
    if prompts_dir.is_dir():
        for p in sorted(prompts_dir.glob("**/*.md")):
            items.append((p, p.stem, SOURCE_FILE))
    # integrations/*/prompts/**/*.md (in-repo + external, recursive)
    for base_dir in _integration_dirs():
        if not base_dir.is_dir():
            continue
        for intg_dir in sorted(base_dir.iterdir()):
            if not intg_dir.is_dir():
                continue
            intg_prompts = intg_dir / "prompts"
            if intg_prompts.is_dir():
                for p in sorted(intg_prompts.glob("**/*.md")):
                    items.append((p, p.stem, SOURCE_INTEGRATION))
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
        description = meta.get("description")
        if isinstance(description, str):
            description = description.strip()
        category = meta.get("category")
        triggers_raw = meta.get("triggers", [])
        if isinstance(triggers_raw, str):
            triggers = [t.strip() for t in triggers_raw.split(",") if t.strip()]
        elif isinstance(triggers_raw, list):
            triggers = triggers_raw
        else:
            triggers = []
        source_path = str(path.resolve())

        try:
            async with async_session() as session:
                existing = await session.get(SkillRow, skill_id)
                if existing is None:
                    row = SkillRow(
                        id=skill_id,
                        name=display_name,
                        description=description,
                        category=category,
                        triggers=triggers,
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
                    existing.description = description
                    existing.category = category
                    existing.triggers = triggers
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
        group = meta.get("group")
        recommended_heartbeat = meta.get("recommended_heartbeat")
        tags = meta.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        # Expand compatible_integrations frontmatter into integration:* tags
        compat = meta.get("compatible_integrations", [])
        if isinstance(compat, str):
            compat = [c.strip() for c in compat.split(",") if c.strip()]
        for ci in compat:
            tag = f"integration:{ci}"
            if tag not in tags:
                tags.append(tag)
        # Expand mc_min_version frontmatter into mc_min_version:* tag
        mc_ver = meta.get("mc_min_version")
        if mc_ver:
            ver_tag = f"mc_min_version:{mc_ver}"
            if ver_tag not in tags:
                tags.append(ver_tag)

        async with async_session() as session:
            stmt = select(PromptTemplate).where(
                PromptTemplate.source_path == source_path,
                PromptTemplate.source_type.in_([SOURCE_FILE, SOURCE_INTEGRATION]),
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()

            if existing is None:
                row = PromptTemplate(
                    name=display_name,
                    description=description,
                    content=raw,
                    category=category,
                    tags=tags if tags else [],
                    group=group,
                    recommended_heartbeat=recommended_heartbeat,
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
                existing.group = group
                existing.recommended_heartbeat = recommended_heartbeat
                existing.content_hash = content_hash
                existing.source_path = source_path
                existing.source_type = source_type
                existing.updated_at = datetime.now(timezone.utc)
                await session.commit()
                counts["updated"] += 1
                logger.info("file_sync: updated prompt template '%s' from %s", display_name, path)

    # Delete orphaned file/integration-managed prompt templates
    async with async_session() as session:
        stmt = select(PromptTemplate).where(
            PromptTemplate.source_type.in_([SOURCE_FILE, SOURCE_INTEGRATION])
        )
        all_file_templates = list((await session.execute(stmt)).scalars().all())
        for row in all_file_templates:
            if row.source_path not in seen_template_paths:
                await session.delete(row)
                counts["deleted"] += 1
                logger.info("file_sync: deleted orphaned prompt template '%s'", row.name)
        await session.commit()

    # --- Carapaces ---
    from app.agent.carapaces import collect_carapace_files
    import yaml as _yaml

    carapace_files = collect_carapace_files()
    seen_carapace_ids: set[str] = set()

    for path, carapace_id, source_type in carapace_files:
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            logger.exception("Cannot read carapace file %s", path)
            counts["errors"].append(f"Cannot read {path}")
            continue

        content_hash = _sha256(raw)
        data = _yaml.safe_load(raw) or {}
        cid = data.get("id", carapace_id)
        seen_carapace_ids.add(cid)
        source_path = str(path.resolve())

        try:
            async with async_session() as session:
                existing = await session.get(CarapaceRow, cid)
                if existing is None:
                    row = CarapaceRow(
                        id=cid,
                        name=data.get("name", cid),
                        description=data.get("description"),
                        skills=data.get("skills", []),
                        local_tools=data.get("local_tools", []),
                        mcp_tools=data.get("mcp_tools", []),
                        pinned_tools=data.get("pinned_tools", []),
                        delegates=data.get("delegates", []),
                        system_prompt_fragment=data.get("system_prompt_fragment"),
                        includes=data.get("includes", []),
                        tags=data.get("tags", []),
                        source_path=source_path,
                        source_type=source_type,
                        content_hash=content_hash,
                        updated_at=datetime.now(timezone.utc),
                    )
                    session.add(row)
                    await session.commit()
                    counts["added"] += 1
                    logger.info("file_sync: added carapace '%s' from %s", cid, path)
                elif existing.content_hash != content_hash:
                    existing.name = data.get("name", cid)
                    existing.description = data.get("description")
                    existing.skills = data.get("skills", [])
                    existing.local_tools = data.get("local_tools", [])
                    existing.mcp_tools = data.get("mcp_tools", [])
                    existing.pinned_tools = data.get("pinned_tools", [])
                    existing.delegates = data.get("delegates", [])
                    existing.system_prompt_fragment = data.get("system_prompt_fragment")
                    existing.includes = data.get("includes", [])
                    existing.tags = data.get("tags", [])
                    existing.source_path = source_path
                    existing.source_type = source_type
                    existing.content_hash = content_hash
                    existing.updated_at = datetime.now(timezone.utc)
                    await session.commit()
                    counts["updated"] += 1
                    logger.info("file_sync: updated carapace '%s' from %s", cid, path)
                else:
                    counts["unchanged"] += 1
                    if existing.source_type != source_type or existing.source_path != source_path:
                        existing.source_type = source_type
                        existing.source_path = source_path
                        await session.commit()
        except Exception:
            logger.exception("file_sync: DB error syncing carapace '%s'", cid)
            counts["errors"].append(f"DB error for carapace '{cid}'")

    # Delete orphaned file/integration carapaces
    if carapace_files:
        async with async_session() as session:
            stmt = select(CarapaceRow).where(
                CarapaceRow.source_type.in_([SOURCE_FILE, SOURCE_INTEGRATION])
            )
            all_file_carapaces = list((await session.execute(stmt)).scalars().all())
            for row in all_file_carapaces:
                if row.id not in seen_carapace_ids:
                    await session.delete(row)
                    counts["deleted"] += 1
                    logger.info("file_sync: deleted orphaned carapace '%s'", row.id)
            await session.commit()
    elif not carapace_files:
        # Log a warning — zero files found might mean a mount issue
        async with async_session() as session:
            existing_count = (await session.execute(
                select(func.count()).select_from(CarapaceRow).where(
                    CarapaceRow.source_type.in_([SOURCE_FILE, SOURCE_INTEGRATION])
                )
            )).scalar_one()
        if existing_count > 0:
            logger.warning(
                "file_sync: found 0 carapace files on disk but %d file-sourced carapaces in DB. "
                "Skipping orphan deletion — possible volume mount issue. cwd=%s",
                existing_count, cwd,
            )

    # Reload carapace registry after sync
    if carapace_files or seen_carapace_ids:
        try:
            from app.agent.carapaces import reload_carapaces
            await reload_carapaces()
        except Exception:
            logger.warning("file_sync: failed to reload carapaces", exc_info=True)

    # --- Workflows ---
    from app.services.workflows import collect_workflow_files
    from app.db.models import Workflow as WorkflowRow
    import yaml as _wf_yaml

    workflow_files = collect_workflow_files()
    seen_workflow_ids: set[str] = set()

    for path, workflow_id, source_type in workflow_files:
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            logger.exception("Cannot read workflow file %s", path)
            counts["errors"].append(f"Cannot read {path}")
            continue

        content_hash = _sha256(raw)
        data = _wf_yaml.safe_load(raw) or {}
        wid = data.get("id", workflow_id)
        seen_workflow_ids.add(wid)
        source_path = str(path.resolve())

        try:
            async with async_session() as session:
                existing = await session.get(WorkflowRow, wid)
                if existing is None:
                    row = WorkflowRow(
                        id=wid,
                        name=data.get("name", wid),
                        description=data.get("description"),
                        params=data.get("params", {}),
                        secrets=data.get("secrets", []),
                        defaults=data.get("defaults", {}),
                        steps=data.get("steps", []),
                        triggers=data.get("triggers", {}),
                        tags=data.get("tags", []),
                        session_mode=data.get("session_mode", "isolated"),
                        source_path=source_path,
                        source_type=source_type,
                        content_hash=content_hash,
                        updated_at=datetime.now(timezone.utc),
                    )
                    session.add(row)
                    await session.commit()
                    counts["added"] += 1
                    logger.info("file_sync: added workflow '%s' from %s", wid, path)
                elif existing.source_type == "manual":
                    # Workflow was detached from file — don't overwrite manual edits
                    counts["unchanged"] += 1
                    logger.debug("file_sync: skipping detached workflow '%s'", wid)
                elif existing.content_hash != content_hash:
                    existing.name = data.get("name", wid)
                    existing.description = data.get("description")
                    existing.params = data.get("params", {})
                    existing.secrets = data.get("secrets", [])
                    existing.defaults = data.get("defaults", {})
                    existing.steps = data.get("steps", [])
                    existing.triggers = data.get("triggers", {})
                    existing.tags = data.get("tags", [])
                    existing.session_mode = data.get("session_mode", "isolated")
                    existing.source_path = source_path
                    existing.source_type = source_type
                    existing.content_hash = content_hash
                    existing.updated_at = datetime.now(timezone.utc)
                    await session.commit()
                    counts["updated"] += 1
                    logger.info("file_sync: updated workflow '%s' from %s", wid, path)
                else:
                    counts["unchanged"] += 1
                    if existing.source_type != source_type or existing.source_path != source_path:
                        existing.source_type = source_type
                        existing.source_path = source_path
                        await session.commit()
        except Exception:
            logger.exception("file_sync: DB error syncing workflow '%s'", wid)
            counts["errors"].append(f"DB error for workflow '{wid}'")

    # Delete orphaned file/integration workflows
    if workflow_files:
        async with async_session() as session:
            stmt = select(WorkflowRow).where(
                WorkflowRow.source_type.in_([SOURCE_FILE, SOURCE_INTEGRATION])
            )
            all_file_workflows = list((await session.execute(stmt)).scalars().all())
            for row in all_file_workflows:
                if row.id not in seen_workflow_ids:
                    await session.delete(row)
                    counts["deleted"] += 1
                    logger.info("file_sync: deleted orphaned workflow '%s'", row.id)
            await session.commit()

    # Reload workflow registry after sync
    if workflow_files or seen_workflow_ids:
        try:
            from app.services.workflows import reload_workflows
            await reload_workflows()
        except Exception:
            logger.warning("file_sync: failed to reload workflows", exc_info=True)

    logger.info(
        "file_sync complete: +%d added, ~%d updated, =%d unchanged, -%d deleted, %d errors",
        counts["added"], counts["updated"], counts["unchanged"],
        counts["deleted"], len(counts["errors"]),
    )
    if counts["errors"]:
        logger.warning("file_sync errors: %s", counts["errors"])

    # Invalidate auto-enrollment caches so next context assembly picks up changes
    try:
        from app.agent.context_assembly import invalidate_skill_auto_enroll_cache
        invalidate_skill_auto_enroll_cache()
    except Exception:
        pass

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
            # Carapaces
            stmt4 = select(CarapaceRow).where(CarapaceRow.source_path == path_str)
            rows4 = list((await session.execute(stmt4)).scalars().all())
            for row in rows4:
                await session.delete(row)
            # Workflows
            from app.db.models import Workflow as WorkflowRow
            stmt5 = select(WorkflowRow).where(WorkflowRow.source_path == path_str)
            rows5 = list((await session.execute(stmt5)).scalars().all())
            for row in rows5:
                await session.delete(row)
            if rows or rows2 or rows3 or rows4 or rows5:
                await session.commit()
                logger.info("file_sync: removed DB rows for deleted file %s", path)
            if rows5:
                try:
                    from app.services.workflows import reload_workflows
                    await reload_workflows()
                except Exception:
                    pass
            if rows4:
                try:
                    from app.agent.carapaces import reload_carapaces
                    await reload_carapaces()
                except Exception:
                    pass
        return

    if path.suffix not in (".md", ".yaml"):
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
        group = meta.get("group")
        recommended_heartbeat = meta.get("recommended_heartbeat")
        tags = meta.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        # Expand compatible_integrations frontmatter into integration:* tags
        compat = meta.get("compatible_integrations", [])
        if isinstance(compat, str):
            compat = [c.strip() for c in compat.split(",") if c.strip()]
        for ci in compat:
            tag = f"integration:{ci}"
            if tag not in tags:
                tags.append(tag)
        # Expand mc_min_version frontmatter into mc_min_version:* tag
        mc_ver = meta.get("mc_min_version")
        if mc_ver:
            ver_tag = f"mc_min_version:{mc_ver}"
            if ver_tag not in tags:
                tags.append(ver_tag)
        async with async_session() as session:
            stmt = select(PromptTemplate).where(
                PromptTemplate.source_path == path_str,
                PromptTemplate.source_type.in_([SOURCE_FILE, SOURCE_INTEGRATION]),
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is None:
                row = PromptTemplate(
                    name=display_name,
                    description=description,
                    content=raw,
                    category=category,
                    tags=tags if tags else [],
                    group=group,
                    recommended_heartbeat=recommended_heartbeat,
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
                existing.group = group
                existing.recommended_heartbeat = recommended_heartbeat
                existing.content_hash = content_hash
                existing.updated_at = datetime.now(timezone.utc)
                await session.commit()
                logger.info("file_sync(watch): updated prompt template '%s'", display_name)
    elif kind == "carapace":
        import yaml as _yaml
        cid = skill_id_or_name
        data = _yaml.safe_load(raw) or {}
        cid = data.get("id", cid)
        async with async_session() as session:
            existing = await session.get(CarapaceRow, cid)
            if existing is None:
                row = CarapaceRow(
                    id=cid,
                    name=data.get("name", cid),
                    description=data.get("description"),
                    skills=data.get("skills", []),
                    local_tools=data.get("local_tools", []),
                    mcp_tools=data.get("mcp_tools", []),
                    pinned_tools=data.get("pinned_tools", []),
                    delegates=data.get("delegates", []),
                    system_prompt_fragment=data.get("system_prompt_fragment"),
                    includes=data.get("includes", []),
                    tags=data.get("tags", []),
                    source_path=path_str,
                    source_type=source_type,
                    content_hash=content_hash,
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(row)
                await session.commit()
                logger.info("file_sync(watch): added carapace '%s'", cid)
            elif existing.content_hash != content_hash:
                existing.name = data.get("name", cid)
                existing.description = data.get("description")
                existing.skills = data.get("skills", [])
                existing.local_tools = data.get("local_tools", [])
                existing.mcp_tools = data.get("mcp_tools", [])
                existing.pinned_tools = data.get("pinned_tools", [])
                existing.delegates = data.get("delegates", [])
                existing.system_prompt_fragment = data.get("system_prompt_fragment")
                existing.includes = data.get("includes", [])
                existing.tags = data.get("tags", [])
                existing.source_path = path_str
                existing.source_type = source_type
                existing.content_hash = content_hash
                existing.updated_at = datetime.now(timezone.utc)
                await session.commit()
                logger.info("file_sync(watch): updated carapace '%s'", cid)
        try:
            from app.agent.carapaces import reload_carapaces
            await reload_carapaces()
        except Exception:
            pass
    elif kind == "workflow":
        import yaml as _yaml
        from app.db.models import Workflow as WorkflowRow
        wid = skill_id_or_name
        data = _yaml.safe_load(raw) or {}
        wid = data.get("id", wid)
        async with async_session() as session:
            existing = await session.get(WorkflowRow, wid)
            if existing is None:
                row = WorkflowRow(
                    id=wid,
                    name=data.get("name", wid),
                    description=data.get("description"),
                    params=data.get("params", {}),
                    secrets=data.get("secrets", []),
                    defaults=data.get("defaults", {}),
                    steps=data.get("steps", []),
                    triggers=data.get("triggers", {}),
                    tags=data.get("tags", []),
                    source_path=path_str,
                    source_type=source_type,
                    content_hash=content_hash,
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(row)
                await session.commit()
                logger.info("file_sync(watch): added workflow '%s'", wid)
            elif existing.content_hash != content_hash:
                existing.name = data.get("name", wid)
                existing.description = data.get("description")
                existing.params = data.get("params", {})
                existing.secrets = data.get("secrets", [])
                existing.defaults = data.get("defaults", {})
                existing.steps = data.get("steps", [])
                existing.triggers = data.get("triggers", {})
                existing.tags = data.get("tags", [])
                existing.source_path = path_str
                existing.source_type = source_type
                existing.content_hash = content_hash
                existing.updated_at = datetime.now(timezone.utc)
                await session.commit()
                logger.info("file_sync(watch): updated workflow '%s'", wid)
        try:
            from app.services.workflows import reload_workflows
            await reload_workflows()
        except Exception:
            pass


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

    # prompts/**/*.md (recursive — supports category subfolders)
    if len(parts) >= 2 and parts[0] == "prompts" and parts[-1].endswith(".md"):
        return ("prompt_template", Path(parts[-1]).stem, None, SOURCE_FILE)

    # integrations/{id}/prompts/**/*.md (recursive — supports category subfolders)
    if len(parts) >= 4 and parts[0] == "integrations" and parts[2] == "prompts" and parts[-1].endswith(".md"):
        return ("prompt_template", Path(parts[-1]).stem, None, SOURCE_INTEGRATION)

    # carapaces/*.yaml
    if len(parts) == 2 and parts[0] == "carapaces" and parts[1].endswith(".yaml"):
        return ("carapace", Path(parts[1]).stem, None, SOURCE_FILE)

    # carapaces/*/carapace.yaml (subdirectory carapaces)
    if len(parts) == 3 and parts[0] == "carapaces" and parts[2] == "carapace.yaml":
        return ("carapace", parts[1], None, SOURCE_FILE)

    # carapaces/*/skills/*.md (carapace-scoped skills)
    if len(parts) == 4 and parts[0] == "carapaces" and parts[2] == "skills" and parts[3].endswith(".md"):
        skill_id = f"carapaces/{parts[1]}/{Path(parts[3]).stem}"
        return ("skill", skill_id, None, SOURCE_FILE)

    # integrations/{id}/carapaces/*.yaml
    if len(parts) == 4 and parts[0] == "integrations" and parts[2] == "carapaces" and parts[3].endswith(".yaml"):
        carapace_id = f"integrations/{parts[1]}/{Path(parts[3]).stem}"
        return ("carapace", carapace_id, None, SOURCE_INTEGRATION)

    # integrations/{id}/carapaces/*/carapace.yaml (subdirectory integration carapaces)
    if len(parts) == 5 and parts[0] == "integrations" and parts[2] == "carapaces" and parts[4] == "carapace.yaml":
        carapace_id = f"integrations/{parts[1]}/{parts[3]}"
        return ("carapace", carapace_id, None, SOURCE_INTEGRATION)

    # integrations/{id}/carapaces/*/skills/*.md (integration carapace-scoped skills)
    if len(parts) == 6 and parts[0] == "integrations" and parts[2] == "carapaces" and parts[4] == "skills" and parts[5].endswith(".md"):
        skill_id = f"integrations/{parts[1]}/carapaces/{parts[3]}/{Path(parts[5]).stem}"
        return ("skill", skill_id, None, SOURCE_INTEGRATION)

    # workflows/*.yaml
    if len(parts) == 2 and parts[0] == "workflows" and parts[1].endswith(".yaml"):
        return ("workflow", Path(parts[1]).stem, None, SOURCE_FILE)

    # integrations/{id}/workflows/*.yaml
    if len(parts) == 4 and parts[0] == "integrations" and parts[2] == "workflows" and parts[3].endswith(".yaml"):
        return ("workflow", Path(parts[3]).stem, None, SOURCE_INTEGRATION)

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
        for d in ["skills", "knowledge", "bots", "integrations", "packages", "prompts", "carapaces", "workflows"]:
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
                    if p.suffix not in (".md", ".yaml"):
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
