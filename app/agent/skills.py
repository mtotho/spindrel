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


async def cascade_skill_deletion(skill_id: str, db) -> dict:
    """Remove a deleted skill from all bot.skills JSONB arrays.

    Returns {"bots_updated": N} for logging.
    """
    from app.db.models import Bot
    from sqlalchemy.orm.attributes import flag_modified

    stats = {"bots_updated": 0}

    bots = (await db.execute(select(Bot))).scalars().all()
    for bot in bots:
        skills = bot.skills or []
        filtered = [s for s in skills if s.get("id") != skill_id]
        if len(filtered) != len(skills):
            bot.skills = filtered
            flag_modified(bot, "skills")
            stats["bots_updated"] += 1

    return stats

_loaded_skills: set[str] = set()


def list_available_skills(skills_dir: Path = SKILLS_DIR) -> list[str]:
    """List skill IDs from the filesystem (flat + folder-layout).

    Flat: `skills/foo.md` → `foo`.
    Folder: `skills/foo/index.md` → `foo`; `skills/foo/bar.md` → `foo/bar`.
    Matches `_walk_skill_files` in `app/services/file_sync.py`.
    """
    if not skills_dir.exists():
        return []
    ids: list[str] = [p.stem for p in skills_dir.glob("*.md")]
    for sub in sorted(skills_dir.iterdir()):
        if not sub.is_dir():
            continue
        for p in sorted(sub.rglob("*.md")):
            rel = p.relative_to(skills_dir)
            parts = list(rel.parts)
            parts[-1] = parts[-1][:-3]
            if parts[-1].lower() in ("index", "readme"):
                parts = parts[:-1]
            if parts:
                ids.append("/".join(parts))
    return ids


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

    # --- Contextual retrieval: generate LLM descriptions for chunks ---
    from app.agent.contextual_retrieval import (
        build_embed_text,
        generate_batch_contexts,
        get_effective_chunking_version,
    )

    cr_chunks = [{"text": cr.content, "index": i} for i, cr in enumerate(chunk_results)]
    cr_descriptions = await generate_batch_contexts(cr_chunks, body, display_name, content_hash)

    # For embedding: compose context_prefix + contextual_description + content
    embed_texts = []
    for i, cr in enumerate(chunk_results):
        embed_texts.append(build_embed_text(
            cr.content,
            context_prefix=cr.context_prefix,
            contextual_description=cr_descriptions[i],
            source_label=source_label,
        ))

    effective_version = get_effective_chunking_version(CHUNKING_VERSION)

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
            doc_meta = {
                    "content_hash": content_hash,
                    "chunking_version": effective_version,
                    "chunk_index": i,
                    "skill_id": skill_id,
                    "skill_name": display_name,
                    "context_prefix": cr.context_prefix,
            }
            if cr_descriptions[i]:
                doc_meta["contextual_description"] = cr_descriptions[i]
            doc = Document(
                content=stored_content,
                embedding=embedding,
                source=f"skill:{skill_id}",
                metadata_=doc_meta,
            )
            db.add(doc)
        await db.commit()

    # Backfill tsvector for hybrid search (non-fatal)
    try:
        async with async_session() as db:
            from sqlalchemy import text as _sa_text
            await db.execute(_sa_text(
                "UPDATE documents SET tsv = to_tsvector('english', content) "
                "WHERE source = :src AND tsv IS NULL"
            ).bindparams(src=f"skill:{skill_id}"))
            await db.commit()
    except Exception:
        logger.debug("TSVector backfill failed for skill %s (expected on SQLite)", skill_id)

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
            from app.agent.contextual_retrieval import get_effective_chunking_version
            effective_version = get_effective_chunking_version(CHUNKING_VERSION)
            existing_hash, existing_version = existing_doc
            if existing_hash == content_hash and existing_version == effective_version:
                logger.debug("Skill '%s' unchanged, skipping", skill_id)
                _loaded_skills.add(skill_id)
                continue
            if existing_version != effective_version:
                logger.info("Skill '%s' chunking version stale (%s → %s), re-embedding",
                            skill_id, existing_version, effective_version)

        await _embed_skill_row(skill_id, row.content, content_hash)
        loaded += 1

    logger.info("Skill loading complete (%d new/updated, %d total)", loaded, len(_loaded_skills))

    # Warm contextual retrieval cache from existing skill embeddings
    if settings.CONTEXTUAL_RETRIEVAL_ENABLED:
        from app.agent.contextual_retrieval import warm_cache_from_metadata
        async with async_session() as db:
            cr_rows = (await db.execute(
                select(
                    Document.metadata_["content_hash"].as_string(),
                    Document.metadata_["chunk_index"].as_integer(),
                    Document.metadata_["contextual_description"].as_string(),
                ).where(Document.source.like("skill:%"))
            )).all()
        warmed = warm_cache_from_metadata(cr_rows)
        if warmed:
            logger.info("Warmed contextual retrieval cache from %d skill chunk(s)", warmed)


async def re_embed_skill(skill_id: str) -> None:
    """Force re-embed a single skill from DB — called after admin edits."""
    async with async_session() as db:
        row = await db.get(SkillRow, skill_id)
        if not row:
            logger.warning("re_embed_skill: skill '%s' not found in DB", skill_id)
            return

    await _embed_skill_row(skill_id, row.content, row.content_hash)
