import hashlib
import logging
import re
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.agent.chunking import CHUNKING_VERSION, chunk_markdown
from app.agent.embeddings import embed_batch as _embed_batch
from app.config import settings
from app.db.engine import async_session
from app.db.models import Document, Skill as SkillRow

logger = logging.getLogger(__name__)

SKILLS_DIR = Path("skills")

_loaded_skills: set[str] = set()


def list_available_skills(skills_dir: Path = SKILLS_DIR) -> list[str]:
    """List skill IDs from DB (for backward compat, falls back to filesystem)."""
    if not skills_dir.exists():
        return []
    return [p.stem for p in skills_dir.glob("*.md")]


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter (between --- markers) from markdown content."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return {}, content
    import yaml
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except Exception:
        meta = {}
    body = content[match.end():]
    return meta, body


async def _embed_skill_row(skill_id: str, content: str, content_hash: str) -> None:
    """Re-embed a skill's chunks into the documents table."""
    meta, body = _parse_frontmatter(content)
    display_name = meta.get("name", skill_id.replace("_", " ").title())
    source_label = f"[Skill: {display_name}]"

    chunk_results = chunk_markdown(body, source_label=source_label, max_chunk=1500)

    if not chunk_results:
        logger.warning("Skill '%s' produced no chunks, skipping embed", skill_id)
        return

    # For embedding: prepend context_prefix for better retrieval
    # For storage: keep only the content (context_prefix is metadata)
    embed_texts = []
    for cr in chunk_results:
        if cr.context_prefix:
            embed_texts.append(f"{cr.context_prefix}\n\n{cr.content}")
        else:
            embed_texts.append(f"{source_label}\n\n{cr.content}")

    logger.info("Embedding skill '%s' (%d chunks)...", skill_id, len(chunk_results))
    try:
        embeddings = await _embed_batch(embed_texts)
    except Exception:
        logger.exception("Failed to embed skill '%s'", skill_id)
        return

    async with async_session() as db:
        await db.execute(delete(Document).where(Document.source == f"skill:{skill_id}"))
        for i, (cr, embedding) in enumerate(zip(chunk_results, embeddings)):
            # Store the content with the source label prefix for display
            stored_content = f"{source_label}\n\n{cr.content}"
            doc = Document(
                content=stored_content,
                embedding=embedding,
                source=f"skill:{skill_id}",
                metadata_={
                    "content_hash": content_hash,
                    "chunking_version": CHUNKING_VERSION,
                    "chunk_index": i,
                    "skill_id": skill_id,
                    "skill_name": display_name,
                    "context_prefix": cr.context_prefix,
                },
            )
            db.add(doc)
        await db.commit()

    _loaded_skills.add(skill_id)
    logger.info("Embedded skill '%s' (%d chunks)", skill_id, len(chunk_results))


async def seed_skills_from_files(skills_dir: Path = SKILLS_DIR) -> None:
    """Seed skills from .md files into DB — only if id doesn't already exist."""
    if not skills_dir.exists():
        logger.info("No skills directory at %s, skipping seed", skills_dir)
        return

    skill_files = sorted(skills_dir.glob("*.md"))
    if not skill_files:
        return

    async with async_session() as db:
        for path in skill_files:
            skill_id = path.stem
            raw = path.read_text()
            content_hash = hashlib.sha256(raw.encode()).hexdigest()
            meta, _ = _parse_frontmatter(raw)
            display_name = meta.get("name", skill_id.replace("_", " ").title())

            stmt = pg_insert(SkillRow).values(
                id=skill_id,
                name=display_name,
                content=raw,
                content_hash=content_hash,
            ).on_conflict_do_nothing(index_elements=["id"])
            await db.execute(stmt)
        await db.commit()
    logger.info("Seeded skills from files (seed-once, no overwrites)")


async def load_skills(skills_dir: Path = SKILLS_DIR) -> None:
    """Load skills from DB, re-embed chunks when content_hash differs."""
    async with async_session() as db:
        skill_rows = (await db.execute(select(SkillRow))).scalars().all()

    if not skill_rows:
        logger.info("No skills in DB, skipping load")
        return

    logger.info("Checking %d skill(s) from DB", len(skill_rows))
    loaded = 0

    for row in skill_rows:
        skill_id = row.id
        content_hash = row.content_hash

        # Check if embedding is up to date (content hash + chunking version)
        async with async_session() as db:
            existing_doc = (await db.execute(
                select(
                    Document.metadata_["content_hash"].as_string(),
                    Document.metadata_["chunking_version"].as_string(),
                )
                .where(Document.source == f"skill:{skill_id}")
                .limit(1)
            )).first()

        if existing_doc:
            existing_hash, existing_version = existing_doc
            if existing_hash == content_hash and existing_version == CHUNKING_VERSION:
                logger.debug("Skill '%s' unchanged, skipping", skill_id)
                _loaded_skills.add(skill_id)
                continue
            if existing_version != CHUNKING_VERSION:
                logger.info("Skill '%s' chunking version stale (%s → %s), re-embedding",
                            skill_id, existing_version, CHUNKING_VERSION)

        await _embed_skill_row(skill_id, row.content, content_hash)
        loaded += 1

    logger.info("Skill loading complete (%d new/updated, %d total)", loaded, len(_loaded_skills))


async def re_embed_skill(skill_id: str) -> None:
    """Force re-embed a single skill from DB — called after admin edits."""
    async with async_session() as db:
        row = await db.get(SkillRow, skill_id)
        if not row:
            logger.warning("re_embed_skill: skill '%s' not found in DB", skill_id)
            return

    await _embed_skill_row(skill_id, row.content, row.content_hash)
