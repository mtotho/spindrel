"""Workspace skills — discover, embed, and retrieve skill .md files from shared workspace filesystems."""
import hashlib
import logging
import os
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.skills import _chunk_markdown, _embed_batch
from app.db.engine import async_session
from app.db.models import Document, SharedWorkspace, SharedWorkspaceBot
from app.services.shared_workspace import shared_workspace_service, SharedWorkspaceError

logger = logging.getLogger(__name__)

# Subdirectory → mode mapping
SKILL_SUBDIRS = {"pinned": "pinned", "rag": "rag", "on-demand": "on_demand"}
# Source prefix for documents table
SOURCE_PREFIX = "workspace_skill"


@dataclass
class WorkspaceSkill:
    workspace_id: str
    source_path: str        # e.g. "common/skills/pinned/coding.md"
    mode: str               # pinned | rag | on_demand
    skill_id: str           # derived: "ws:{workspace_id_short}:{path_hash}"
    bot_id: str | None      # None for common skills
    content: str
    content_hash: str
    display_name: str       # derived from filename


def _mode_from_path(rel_path: str) -> str:
    """Determine skill mode from the path within skills/ directory.

    pinned/  → pinned
    rag/     → rag
    on-demand/ → on_demand
    top-level (no subdir) → pinned (default)
    """
    parts = rel_path.split("/")
    # Find the part after "skills/"
    try:
        idx = parts.index("skills")
    except ValueError:
        return "pinned"
    after_skills = parts[idx + 1:]
    if len(after_skills) >= 2:
        subdir = after_skills[0]
        if subdir in SKILL_SUBDIRS:
            return SKILL_SUBDIRS[subdir]
    return "pinned"


def _skill_id(workspace_id: str, source_path: str) -> str:
    """Generate a stable skill ID from workspace + path."""
    path_hash = hashlib.sha256(source_path.encode()).hexdigest()[:12]
    ws_short = workspace_id.replace("-", "")[:8]
    return f"ws:{ws_short}:{path_hash}"


def _display_name(source_path: str) -> str:
    """Derive display name from filename."""
    basename = os.path.basename(source_path)
    name = os.path.splitext(basename)[0]
    return name.replace("_", " ").replace("-", " ").title()


def discover_workspace_skills(
    workspace_id: str,
    bot_id: str | None = None,
) -> list[WorkspaceSkill]:
    """Scan workspace filesystem for skill .md files.

    Scans:
    - common/skills/ (and subdirs pinned/, rag/, on-demand/) → common skills (bot_id=None)
    - bots/{bot_id}/skills/ (and subdirs) → bot-specific skills

    If bot_id is provided, only scans common + that bot's skills.
    If bot_id is None, scans common skills only.
    """
    skills: list[WorkspaceSkill] = []

    def _scan_skills_dir(base_path: str, target_bot_id: str | None):
        """Recursively scan a skills/ directory for .md files."""
        try:
            entries = shared_workspace_service.list_files(workspace_id, base_path)
        except (SharedWorkspaceError, OSError):
            return

        for entry in entries:
            full_path = entry["path"]
            if entry["is_dir"]:
                # Recurse into subdirectories (pinned/, rag/, on-demand/)
                _scan_skills_dir(full_path, target_bot_id)
            elif entry["name"].endswith(".md"):
                try:
                    file_data = shared_workspace_service.read_file(workspace_id, full_path)
                    content = file_data["content"]
                except (SharedWorkspaceError, OSError):
                    continue
                content_hash = hashlib.sha256(content.encode()).hexdigest()
                mode = _mode_from_path(full_path)
                sid = _skill_id(workspace_id, full_path)
                skills.append(WorkspaceSkill(
                    workspace_id=workspace_id,
                    source_path=full_path,
                    mode=mode,
                    skill_id=sid,
                    bot_id=target_bot_id,
                    content=content,
                    content_hash=content_hash,
                    display_name=_display_name(full_path),
                ))

    # Scan common skills
    _scan_skills_dir("common/skills", None)

    # Scan bot-specific skills
    if bot_id:
        _scan_skills_dir(f"bots/{bot_id}/skills", bot_id)

    return skills


async def embed_workspace_skills(workspace_id: str) -> dict:
    """Discover all workspace skills, chunk, embed into documents table.

    Returns stats: {total, embedded, unchanged, errors}
    """
    # Discover all skills (common only — bot-specific are also common skills scope)
    all_skills = discover_workspace_skills(workspace_id, bot_id=None)

    # Also discover for all bots in the workspace
    async with async_session() as db:
        sw_bots = (await db.execute(
            select(SharedWorkspaceBot.bot_id)
            .where(SharedWorkspaceBot.workspace_id == workspace_id)
        )).scalars().all()

    for bid in sw_bots:
        bot_skills = discover_workspace_skills(workspace_id, bot_id=bid)
        # Only add bot-specific skills (common already included)
        existing_paths = {s.source_path for s in all_skills}
        for bs in bot_skills:
            if bs.source_path not in existing_paths:
                all_skills.append(bs)
                existing_paths.add(bs.source_path)

    stats = {"total": len(all_skills), "embedded": 0, "unchanged": 0, "errors": 0}

    for skill in all_skills:
        source = f"{SOURCE_PREFIX}:{workspace_id}:{skill.source_path}"
        # Check if already embedded with same hash
        async with async_session() as db:
            existing_hash = (await db.execute(
                select(Document.metadata_["content_hash"].as_string())
                .where(Document.source == source)
                .limit(1)
            )).scalar_one_or_none()

        if existing_hash == skill.content_hash:
            stats["unchanged"] += 1
            continue

        # Chunk and embed
        chunks = _chunk_markdown(skill.content, skill.display_name)
        if not chunks:
            stats["errors"] += 1
            continue

        try:
            embeddings = await _embed_batch(chunks)
        except Exception:
            logger.exception("Failed to embed workspace skill %s", skill.source_path)
            stats["errors"] += 1
            continue

        async with async_session() as db:
            await db.execute(delete(Document).where(Document.source == source))
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                doc = Document(
                    content=chunk,
                    embedding=embedding,
                    source=source,
                    metadata_={
                        "content_hash": skill.content_hash,
                        "chunk_index": i,
                        "skill_id": skill.skill_id,
                        "skill_name": skill.display_name,
                        "workspace_id": workspace_id,
                        "bot_id": skill.bot_id,
                        "mode": skill.mode,
                        "source_path": skill.source_path,
                    },
                )
                db.add(doc)
            await db.commit()

        stats["embedded"] += 1
        logger.info("Embedded workspace skill %s (%d chunks)", skill.source_path, len(chunks))

    logger.info(
        "Workspace skill embedding complete for %s: %d total, %d embedded, %d unchanged, %d errors",
        workspace_id, stats["total"], stats["embedded"], stats["unchanged"], stats["errors"],
    )
    return stats


async def get_workspace_skills_for_bot(
    workspace_id: str,
    bot_id: str,
) -> dict[str, list[WorkspaceSkill]]:
    """Return workspace skills grouped by mode: {pinned: [...], rag: [...], on_demand: [...]}.

    Includes common skills + bot-specific skills.
    """
    skills = discover_workspace_skills(workspace_id, bot_id=bot_id)
    result: dict[str, list[WorkspaceSkill]] = {"pinned": [], "rag": [], "on_demand": []}
    for s in skills:
        if s.mode in result:
            result[s.mode].append(s)
    return result


async def list_workspace_skill_files(workspace_id: str) -> list[dict]:
    """List all discovered skill files with metadata (for admin UI)."""
    all_skills = discover_workspace_skills(workspace_id, bot_id=None)

    # Also discover for all bots
    async with async_session() as db:
        sw_bots = (await db.execute(
            select(SharedWorkspaceBot.bot_id)
            .where(SharedWorkspaceBot.workspace_id == workspace_id)
        )).scalars().all()

    existing_paths = {s.source_path for s in all_skills}
    for bid in sw_bots:
        bot_skills = discover_workspace_skills(workspace_id, bot_id=bid)
        for bs in bot_skills:
            if bs.source_path not in existing_paths:
                all_skills.append(bs)
                existing_paths.add(bs.source_path)

    return [
        {
            "skill_id": s.skill_id,
            "source_path": s.source_path,
            "mode": s.mode,
            "bot_id": s.bot_id,
            "display_name": s.display_name,
            "content_hash": s.content_hash,
        }
        for s in all_skills
    ]
