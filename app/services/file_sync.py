"""File-based sync service for skills.

Scans structured directories on startup and via a watchfiles watcher.
Hash-based change detection; auto-deletes orphaned DB rows.

Supported directories:
  skills/*.md                        → skills (source_type='file', global)
  bots/{id}/skills/*.md              → skills (source_type='file', name='bots/{id}/{stem}')
  integrations/{id}/skills/*.md      → skills (source_type='integration')
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
from app.db.models import PromptTemplate, Skill as SkillRow

logger = logging.getLogger(__name__)

# Source type constants
SOURCE_FILE = "file"
SOURCE_INTEGRATION = "integration"
SOURCE_MANUAL = "manual"
SOURCE_TOOL = "tool"


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


_SKILL_ID_PATTERN = re.compile(r"^[a-z0-9_/-]+$")


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


def _resolve_skill_id(default_id: str, meta: dict) -> str:
    """Return frontmatter `id:` if present and valid; else path-derived default.

    An `id:` override lets a skill keep a stable logical ID across filesystem
    moves — without it, moving a file cascades enrollment rows via the
    bot_skill_enrollment / channel_skill_enrollment FKs. The override must
    match ``^[a-z0-9_/-]+$`` after stripping whitespace; otherwise we fall
    back to the default and log a warning so bad overrides are visible.
    """
    raw = meta.get("id")
    if not isinstance(raw, str):
        return default_id
    candidate = raw.strip()
    if not candidate:
        return default_id
    if not _SKILL_ID_PATTERN.match(candidate):
        logger.warning(
            "file_sync: invalid skill id override %r — falling back to %r",
            raw, default_id,
        )
        return default_id
    return candidate


def _extract_skill_metadata(raw: str, skill_id: str) -> dict[str, Any]:
    """Extract display name, description, category, and triggers from skill frontmatter."""
    meta, _ = _parse_frontmatter(raw)
    display_name = meta.get("name", skill_id.replace("_", " ").replace("/", " / ").title())
    description = meta.get("description")
    if isinstance(description, str):
        description = description.strip()
    triggers_raw = meta.get("triggers", [])
    if isinstance(triggers_raw, str):
        triggers = [t.strip() for t in triggers_raw.split(",") if t.strip()]
    elif isinstance(triggers_raw, list):
        triggers = triggers_raw
    else:
        triggers = []
    return {
        "name": display_name,
        "description": description,
        "category": meta.get("category"),
        "triggers": triggers,
    }


def _chunk_markdown(body: str, skill_name: str, max_chunk: int = 1500) -> list[str]:
    from app.agent.skills import _chunk_markdown as _chunk
    return _chunk(body, skill_name, max_chunk)


async def _embed_skill_from_content(skill_id: str, content: str, content_hash: str) -> None:
    """Re-embed a skill row using the shared skill embedding logic."""
    from app.agent.skills import _embed_skill_row
    await _embed_skill_row(skill_id, content, content_hash)


def _integration_dirs() -> list[Path]:
    """Return all integration/package directories.

    Includes in-repo ``integrations/`` + ``packages/`` plus every directory
    returned by ``effective_integration_dirs()`` (SPINDREL_HOME, legacy
    INTEGRATION_DIRS, runtime-added dirs).
    """
    dirs = [Path("integrations"), Path("packages")]
    try:
        from app.services.paths import effective_integration_dirs
        for p in effective_integration_dirs():
            path = Path(p)
            if path.is_dir() and path not in dirs:
                dirs.append(path)
    except Exception:
        logger.warning("Could not resolve effective_integration_dirs", exc_info=True)
    return dirs


def _walk_skill_files(base: Path, prefix: str = "") -> list[tuple[Path, str]]:
    """Return (path, skill_id) for every .md under `base`, supporting folder-layout skills.

    Layout:
      <base>/*.md                          → skill_id = prefix + stem
      <base>/<name>/index.md | README.md   → skill_id = prefix + <name>   (folder entry)
      <base>/<name>/<sub>.md               → skill_id = prefix + <name>/<sub>
      <base>/<name>/<sub>/<child>.md       → skill_id = prefix + <name>/<sub>/<child>

    Folder layout lets one skill fan out into sub-skills loadable on demand
    via `get_skill("parent/child")`. Both layouts coexist.
    """
    results: list[tuple[Path, str]] = []
    if not base.is_dir():
        return results
    for p in sorted(base.glob("*.md")):
        results.append((p, f"{prefix}{p.stem}"))
    for sub in sorted(base.iterdir()):
        if not sub.is_dir():
            continue
        for p in sorted(sub.rglob("*.md")):
            rel = p.relative_to(base)
            parts = list(rel.parts)
            parts[-1] = parts[-1][:-3]  # strip ".md"
            if parts[-1].lower() in ("index", "readme"):
                parts = parts[:-1]
            if not parts:
                continue  # defensive — shouldn't happen given the .rglob
            results.append((p, prefix + "/".join(parts)))
    return results


def _collect_skill_files() -> list[tuple[Path, str, str]]:
    """Return (path, skill_id, source_type) for all discoverable skill .md files.

    source_type is 'file' or 'integration'.
    skill_id is the logical key (used as DB primary key).
    """
    items: list[tuple[Path, str, str]] = []

    # skills/*.md + skills/<name>/**/*.md (global, flat or folder-layout)
    for p, skill_id in _walk_skill_files(Path("skills")):
        items.append((p, skill_id, SOURCE_FILE))

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
    # Skip inactive (disabled or unconfigured) integrations
    try:
        from app.services.integration_settings import inactive_integration_ids
        _inactive = inactive_integration_ids()
    except Exception:
        _inactive = set()
    for base_dir in _integration_dirs():
        if not base_dir.is_dir():
            continue
        prefix = base_dir.name  # "integrations", "packages", or external dir name
        for intg_dir in sorted(base_dir.iterdir()):
            if not intg_dir.is_dir() or intg_dir.name in _inactive:
                continue
            intg_skills = intg_dir / "skills"
            if intg_skills.is_dir():
                for p in sorted(intg_skills.glob("*.md")):
                    skill_id = f"{prefix}/{intg_dir.name}/{p.stem}"
                    items.append((p, skill_id, SOURCE_INTEGRATION))

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
    try:
        from app.services.integration_settings import inactive_integration_ids
        _inactive_pt = inactive_integration_ids()
    except Exception:
        _inactive_pt = set()
    for base_dir in _integration_dirs():
        if not base_dir.is_dir():
            continue
        for intg_dir in sorted(base_dir.iterdir()):
            if not intg_dir.is_dir() or intg_dir.name in _inactive_pt:
                continue
            intg_prompts = intg_dir / "prompts"
            if intg_prompts.is_dir():
                for p in sorted(intg_prompts.glob("**/*.md")):
                    items.append((p, p.stem, SOURCE_INTEGRATION))
    return items


# ===== Cluster 10 file_sync stage helpers =====
#
# Both `sync_all_files` (full disk → DB scan) and `sync_changed_file` (single
# watch event) upsert the same three resource kinds (Skill, PromptTemplate,
# Workflow) with byte-equivalent SQL. The helpers below collapse that
# duplication. The `log_path` kwarg threads two variants of the same log
# line — when None, the helper formats the watch-mode message
# ("file_sync(watch): added skill 'X'") and skips sync_all-only branches
# (manual-skip on workflows, source-drift fix on unchanged). When truthy,
# the full sync_all behavior runs.
#
# Helpers raise on DB error; callers wrap (sync_all_files records into
# counts["errors"]; watch_files() catches at the outer loop). This preserves
# today's two error-handling shapes.


def _log_action(action: str, kind: str, ident: str, log_path: Path | None) -> str:
    """Format a sync log message in either watch or sync_all style."""
    if log_path is None:
        return f"file_sync(watch): {action} {kind} '{ident}'"
    return f"file_sync: {action} {kind} '{ident}' from {log_path}"


async def _upsert_skill_row(
    *,
    skill_id: str,
    raw: str,
    source_path: str,
    source_type: str,
    log_path: Path | None,
) -> str:
    """Upsert a Skill row from raw markdown. Returns 'added', 'updated', or 'unchanged'."""
    content_hash = _sha256(raw)
    skill_meta = _extract_skill_metadata(raw, skill_id)
    is_watch = log_path is None

    async with async_session() as session:
        existing = await session.get(SkillRow, skill_id)
        if existing is None:
            row = SkillRow(
                id=skill_id,
                name=skill_meta["name"],
                description=skill_meta["description"],
                category=skill_meta["category"],
                triggers=skill_meta["triggers"],
                content=raw,
                content_hash=content_hash,
                source_path=source_path,
                source_type=source_type,
                updated_at=datetime.now(timezone.utc),
            )
            session.add(row)
            await session.commit()
            logger.info(_log_action("added", "skill", skill_id, log_path))
            await _embed_skill_from_content(skill_id, raw, content_hash)
            return "added"
        if existing.content_hash != content_hash:
            existing.name = skill_meta["name"]
            existing.description = skill_meta["description"]
            existing.category = skill_meta["category"]
            existing.triggers = skill_meta["triggers"]
            existing.content = raw
            existing.content_hash = content_hash
            existing.source_path = source_path
            existing.source_type = source_type
            existing.updated_at = datetime.now(timezone.utc)
            await session.commit()
            logger.info(_log_action("updated", "skill", skill_id, log_path))
            await _embed_skill_from_content(skill_id, raw, content_hash)
            return "updated"
        # Unchanged — sync_all also patches drifted source metadata silently.
        if not is_watch and (
            existing.source_type != source_type or existing.source_path != source_path
        ):
            existing.source_type = source_type
            existing.source_path = source_path
            await session.commit()
        return "unchanged"


def _build_prompt_template_fields(raw: str, name: str) -> dict[str, Any]:
    """Parse frontmatter into PromptTemplate column values shared by both wrappers."""
    meta, _ = _parse_frontmatter(raw)
    display_name = meta.get("name", name.replace("_", " ").replace("-", " ").title())
    category = meta.get("category")
    description = meta.get("description")
    group = meta.get("group")
    recommended_heartbeat = meta.get("recommended_heartbeat")
    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    mc_ver = meta.get("mc_min_version")
    if mc_ver:
        ver_tag = f"mc_min_version:{mc_ver}"
        if ver_tag not in tags:
            tags.append(ver_tag)
    return {
        "name": display_name,
        "description": description,
        "category": category,
        "tags": tags if tags else [],
        "group": group,
        "recommended_heartbeat": recommended_heartbeat,
    }


async def _upsert_prompt_template_row(
    *,
    name: str,
    raw: str,
    source_path: str,
    source_type: str,
    log_path: Path | None,
) -> str:
    """Upsert a PromptTemplate row. Returns 'added', 'updated', or 'unchanged'."""
    content_hash = _sha256(raw)
    fields = _build_prompt_template_fields(raw, name)
    is_watch = log_path is None

    async with async_session() as session:
        stmt = select(PromptTemplate).where(
            PromptTemplate.source_path == source_path,
            PromptTemplate.source_type.in_([SOURCE_FILE, SOURCE_INTEGRATION]),
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing is None:
            row = PromptTemplate(
                name=fields["name"],
                description=fields["description"],
                content=raw,
                category=fields["category"],
                tags=fields["tags"],
                group=fields["group"],
                recommended_heartbeat=fields["recommended_heartbeat"],
                source_type=source_type,
                source_path=source_path,
                content_hash=content_hash,
            )
            session.add(row)
            await session.commit()
            logger.info(_log_action("added", "prompt template", fields["name"], log_path))
            return "added"
        if existing.content_hash != content_hash:
            existing.name = fields["name"]
            existing.description = fields["description"]
            existing.content = raw
            existing.category = fields["category"]
            existing.tags = fields["tags"]
            existing.group = fields["group"]
            existing.recommended_heartbeat = fields["recommended_heartbeat"]
            existing.content_hash = content_hash
            if not is_watch:
                existing.source_path = source_path
                existing.source_type = source_type
            existing.updated_at = datetime.now(timezone.utc)
            await session.commit()
            logger.info(_log_action("updated", "prompt template", fields["name"], log_path))
            return "updated"
        return "unchanged"


async def _upsert_workflow_row(
    *,
    workflow_id: str,
    raw: str,
    source_path: str,
    source_type: str,
    log_path: Path | None,
) -> tuple[str, str]:
    """Upsert a Workflow row. Returns (status, resolved_workflow_id).

    `status` is 'added', 'updated', or 'unchanged'. The resolved id may
    differ from the path-derived `workflow_id` when the YAML contains an
    explicit `id:` field.
    """
    import yaml as _yaml
    from app.db.models import Workflow as WorkflowRow

    is_watch = log_path is None
    content_hash = _sha256(raw)
    data = _yaml.safe_load(raw) or {}
    wid = data.get("id", workflow_id)

    async with async_session() as session:
        existing = await session.get(WorkflowRow, wid)
        if existing is None:
            kwargs: dict[str, Any] = dict(
                id=wid,
                name=data.get("name", wid),
                description=data.get("description"),
                params=data.get("params", {}),
                secrets=data.get("secrets", []),
                defaults=data.get("defaults", {}),
                steps=data.get("steps", []),
                triggers=data.get("triggers", {}),
                tags=data.get("tags", []),
                source_path=source_path,
                source_type=source_type,
                content_hash=content_hash,
                updated_at=datetime.now(timezone.utc),
            )
            if not is_watch:
                kwargs["session_mode"] = data.get("session_mode", "isolated")
            row = WorkflowRow(**kwargs)
            session.add(row)
            await session.commit()
            logger.info(_log_action("added", "workflow", wid, log_path))
            return ("added", wid)
        if (not is_watch) and existing.source_type == "manual":
            logger.debug("file_sync: skipping detached workflow '%s'", wid)
            return ("unchanged", wid)
        if existing.content_hash != content_hash:
            existing.name = data.get("name", wid)
            existing.description = data.get("description")
            existing.params = data.get("params", {})
            existing.secrets = data.get("secrets", [])
            existing.defaults = data.get("defaults", {})
            existing.steps = data.get("steps", [])
            existing.triggers = data.get("triggers", {})
            existing.tags = data.get("tags", [])
            if not is_watch:
                existing.session_mode = data.get("session_mode", "isolated")
            existing.source_path = source_path
            existing.source_type = source_type
            existing.content_hash = content_hash
            existing.updated_at = datetime.now(timezone.utc)
            await session.commit()
            logger.info(_log_action("updated", "workflow", wid, log_path))
            return ("updated", wid)
        if not is_watch and (
            existing.source_type != source_type or existing.source_path != source_path
        ):
            existing.source_type = source_type
            existing.source_path = source_path
            await session.commit()
        return ("unchanged", wid)


async def _delete_orphan_skills(
    *, seen_ids: set[str], any_files_on_disk: bool, cwd: str
) -> tuple[int, list[str]]:
    """Delete file/integration-sourced skill rows whose IDs aren't in `seen_ids`.

    When `any_files_on_disk` is False, skips deletion if any rows exist
    (likely a volume-mount issue) and returns an error message instead.
    Returns (deleted_count, error_messages).
    """
    if any_files_on_disk:
        deleted = 0
        async with async_session() as session:
            stmt = select(SkillRow).where(
                SkillRow.source_type.in_([SOURCE_FILE, SOURCE_INTEGRATION])
            )
            all_file_skills = list((await session.execute(stmt)).scalars().all())
            for row in all_file_skills:
                if row.id not in seen_ids:
                    await session.delete(row)
                    deleted += 1
                    logger.info("file_sync: deleted orphaned skill '%s'", row.id)
            await session.commit()
        return (deleted, [])

    # Zero files on disk — likely a mount issue. Skip deletion.
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
        return (0, [
            f"Found 0 files on disk but {existing_count} file-sourced skills in DB — "
            f"skipping orphan deletion (possible mount issue, cwd={cwd})"
        ])
    return (0, [])


async def _delete_orphan_prompt_templates(*, seen_paths: set[str]) -> int:
    """Delete file/integration-managed prompt templates whose source_path isn't in `seen_paths`."""
    deleted = 0
    async with async_session() as session:
        stmt = select(PromptTemplate).where(
            PromptTemplate.source_type.in_([SOURCE_FILE, SOURCE_INTEGRATION])
        )
        all_file_templates = list((await session.execute(stmt)).scalars().all())
        for row in all_file_templates:
            if row.source_path not in seen_paths:
                await session.delete(row)
                deleted += 1
                logger.info("file_sync: deleted orphaned prompt template '%s'", row.name)
        await session.commit()
    return deleted


async def _delete_orphan_workflows(*, seen_ids: set[str]) -> int:
    """Delete file/integration workflows whose IDs aren't in `seen_ids`."""
    from app.db.models import Workflow as WorkflowRow
    deleted = 0
    async with async_session() as session:
        stmt = select(WorkflowRow).where(
            WorkflowRow.source_type.in_([SOURCE_FILE, SOURCE_INTEGRATION])
        )
        all_file_workflows = list((await session.execute(stmt)).scalars().all())
        for row in all_file_workflows:
            if row.id not in seen_ids:
                await session.delete(row)
                deleted += 1
                logger.info("file_sync: deleted orphaned workflow '%s'", row.id)
        await session.commit()
    return deleted


async def _delete_rows_by_source_path(*, path_str: str) -> tuple[bool, bool]:
    """Delete Skill / PromptTemplate / Workflow rows whose source_path == path_str.

    Returns (any_deleted, workflow_deleted) — the latter signals the caller
    to reload the workflow registry.
    """
    from app.db.models import Workflow as WorkflowRow
    async with async_session() as session:
        skill_rows = list(
            (await session.execute(select(SkillRow).where(SkillRow.source_path == path_str)))
            .scalars().all()
        )
        for row in skill_rows:
            await session.delete(row)
        template_rows = list(
            (await session.execute(
                select(PromptTemplate).where(PromptTemplate.source_path == path_str)
            )).scalars().all()
        )
        for row in template_rows:
            await session.delete(row)
        workflow_rows = list(
            (await session.execute(
                select(WorkflowRow).where(WorkflowRow.source_path == path_str)
            )).scalars().all()
        )
        for row in workflow_rows:
            await session.delete(row)
        any_deleted = bool(skill_rows or template_rows or workflow_rows)
        if any_deleted:
            await session.commit()
        return (any_deleted, bool(workflow_rows))


# ===== End Cluster 10 file_sync stage helpers =====


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

    for path, default_skill_id, source_type in skill_files:
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            logger.exception("Cannot read skill file %s", path)
            counts["errors"].append(f"Cannot read {path}")
            # Protect the existing DB row from orphan deletion when read fails
            seen_skill_ids.add(default_skill_id)
            continue

        meta, _ = _parse_frontmatter(raw)
        skill_id = _resolve_skill_id(default_skill_id, meta)

        if skill_id in seen_skill_ids:
            logger.warning(
                "file_sync: duplicate skill id '%s' — second occurrence at %s skipped "
                "(check for conflicting `id:` frontmatter override)",
                skill_id, path,
            )
            counts["errors"].append(f"Duplicate skill id '{skill_id}' at {path}")
            continue
        seen_skill_ids.add(skill_id)

        try:
            status = await _upsert_skill_row(
                skill_id=skill_id,
                raw=raw,
                source_path=str(path.resolve()),
                source_type=source_type,
                log_path=path,
            )
        except Exception:
            logger.exception("file_sync: DB error syncing skill '%s'", skill_id)
            counts["errors"].append(f"DB error for skill '{skill_id}'")
            continue
        counts[status] = counts.get(status, 0) + 1

    skill_deleted, skill_errors = await _delete_orphan_skills(
        seen_ids=seen_skill_ids,
        any_files_on_disk=bool(skill_files),
        cwd=cwd,
    )
    counts["deleted"] += skill_deleted
    counts["errors"].extend(skill_errors)

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

        try:
            status = await _upsert_prompt_template_row(
                name=name,
                raw=raw,
                source_path=source_path,
                source_type=source_type,
                log_path=path,
            )
        except Exception:
            logger.exception("file_sync: DB error syncing prompt template '%s'", name)
            continue
        counts[status] = counts.get(status, 0) + 1

    counts["deleted"] += await _delete_orphan_prompt_templates(seen_paths=seen_template_paths)

    # --- Workflows ---
    from app.services.workflows import collect_workflow_files

    workflow_files = collect_workflow_files()
    seen_workflow_ids: set[str] = set()

    for path, workflow_id, source_type in workflow_files:
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            logger.exception("Cannot read workflow file %s", path)
            counts["errors"].append(f"Cannot read {path}")
            continue

        try:
            status, wid = await _upsert_workflow_row(
                workflow_id=workflow_id,
                raw=raw,
                source_path=str(path.resolve()),
                source_type=source_type,
                log_path=path,
            )
        except Exception:
            logger.exception("file_sync: DB error syncing workflow '%s'", workflow_id)
            counts["errors"].append(f"DB error for workflow '{workflow_id}'")
            continue
        seen_workflow_ids.add(wid)
        counts[status] = counts.get(status, 0) + 1

    if workflow_files:
        counts["deleted"] += await _delete_orphan_workflows(seen_ids=seen_workflow_ids)

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

    # Invalidate auto-enrollment and skill index caches so next context assembly picks up changes
    try:
        from app.agent.context_assembly import invalidate_skill_auto_enroll_cache
        invalidate_skill_auto_enroll_cache()
        from app.agent.rag import invalidate_skill_index_cache
        invalidate_skill_index_cache()
    except Exception:
        pass

    return counts


async def sync_changed_file(path: Path) -> None:
    """Handle a single file change event from the watcher."""
    path = path.resolve()
    path_str = str(path)

    if not path.exists():
        any_deleted, workflow_deleted = await _delete_rows_by_source_path(path_str=path_str)
        if any_deleted:
            logger.info("file_sync: removed DB rows for deleted file %s", path)
        if workflow_deleted:
            try:
                from app.services.workflows import reload_workflows
                await reload_workflows()
            except Exception:
                pass
        return

    if path.suffix not in (".md", ".yaml"):
        return

    raw = path.read_text(encoding="utf-8")

    # Determine what kind of file this is by checking its location
    rel_parts = _classify_path(path)
    if rel_parts is None:
        return

    kind, skill_id_or_name, _bot_id, source_type = rel_parts

    if kind == "skill":
        await _upsert_skill_row(
            skill_id=skill_id_or_name,
            raw=raw,
            source_path=path_str,
            source_type=source_type,
            log_path=None,
        )
    elif kind == "prompt_template":
        await _upsert_prompt_template_row(
            name=skill_id_or_name,
            raw=raw,
            source_path=path_str,
            source_type=source_type,
            log_path=None,
        )
    elif kind == "workflow":
        await _upsert_workflow_row(
            workflow_id=skill_id_or_name,
            raw=raw,
            source_path=path_str,
            source_type=source_type,
            log_path=None,
        )
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

    # prompts/**/*.md (recursive — supports category subfolders)
    if len(parts) >= 2 and parts[0] == "prompts" and parts[-1].endswith(".md"):
        return ("prompt_template", Path(parts[-1]).stem, None, SOURCE_FILE)

    # integrations/{id}/prompts/**/*.md (recursive — supports category subfolders)
    if len(parts) >= 4 and parts[0] == "integrations" and parts[2] == "prompts" and parts[-1].endswith(".md"):
        return ("prompt_template", Path(parts[-1]).stem, None, SOURCE_INTEGRATION)

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
        for d in ["skills", "bots", "integrations", "packages", "prompts", "workflows"]:
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
