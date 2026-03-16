import hashlib
import logging
import re
from pathlib import Path

from openai import AsyncOpenAI
from sqlalchemy import delete, select

from app.config import settings
from app.db.engine import async_session
from app.db.models import Document

logger = logging.getLogger(__name__)

SKILLS_DIR = Path("skills")

_client = AsyncOpenAI(
    base_url=settings.LITELLM_BASE_URL,
    api_key=settings.LITELLM_API_KEY,
    timeout=120.0,
)

_loaded_skills: set[str] = set()


def list_available_skills(skills_dir: Path = SKILLS_DIR) -> list[str]:
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


def _chunk_markdown(body: str, skill_name: str, max_chunk: int = 1500) -> list[str]:
    """Split markdown into chunks by h2 sections, respecting size limits."""
    sections = re.split(r"(?=^## )", body, flags=re.MULTILINE)

    chunks: list[str] = []
    for section in sections:
        section = section.strip()
        if not section:
            continue

        if len(section) <= max_chunk:
            chunks.append(section)
        else:
            paragraphs = section.split("\n\n")
            current = ""
            for para in paragraphs:
                if current and len(current) + len(para) + 2 > max_chunk:
                    chunks.append(current.strip())
                    current = para
                else:
                    current += ("\n\n" if current else "") + para
            if current.strip():
                chunks.append(current.strip())

    return [f"[Skill: {skill_name}]\n\n{chunk}" for chunk in chunks if chunk]


async def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts via LiteLLM embeddings endpoint."""
    response = await _client.embeddings.create(
        model=settings.EMBEDDING_MODEL,
        input=texts,
    )
    return [item.embedding for item in response.data]


async def load_skills(skills_dir: Path = SKILLS_DIR) -> None:
    """Scan skills directory, chunk + embed any new/changed files, upsert to DB."""
    if not skills_dir.exists():
        logger.info("No skills directory at %s, skipping", skills_dir)
        return

    skill_files = sorted(skills_dir.glob("*.md"))
    if not skill_files:
        logger.info("No .md files in %s", skills_dir)
        return

    logger.info("Checking %d skill file(s) in %s", len(skill_files), skills_dir)
    loaded = 0

    async with async_session() as db:
        for path in skill_files:
            skill_id = path.stem
            raw = path.read_text()
            content_hash = hashlib.sha256(raw.encode()).hexdigest()

            existing = await db.execute(
                select(Document.metadata_["content_hash"].as_string())
                .where(Document.source == f"skill:{skill_id}")
                .limit(1)
            )
            existing_hash = existing.scalar_one_or_none()

            if existing_hash == content_hash:
                logger.debug("Skill '%s' unchanged, skipping", skill_id)
                _loaded_skills.add(skill_id)
                continue

            meta, body = _parse_frontmatter(raw)
            display_name = meta.get("name", skill_id.replace("_", " ").title())
            chunks = _chunk_markdown(body, display_name)

            if not chunks:
                logger.warning("Skill '%s' produced no chunks, skipping", skill_id)
                continue

            logger.info("Embedding skill '%s' (%d chunks)...", skill_id, len(chunks))

            try:
                embeddings = await _embed_batch(chunks)
            except Exception:
                logger.exception("Failed to embed skill '%s', skipping", skill_id)
                continue

            await db.execute(
                delete(Document).where(Document.source == f"skill:{skill_id}")
            )

            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                doc = Document(
                    content=chunk,
                    embedding=embedding,
                    source=f"skill:{skill_id}",
                    metadata_={
                        "content_hash": content_hash,
                        "chunk_index": i,
                        "skill_id": skill_id,
                        "skill_name": display_name,
                    },
                )
                db.add(doc)

            await db.commit()
            _loaded_skills.add(skill_id)
            loaded += 1
            logger.info("Loaded skill '%s' (%d chunks embedded)", skill_id, len(chunks))

    logger.info("Skill loading complete (%d new/updated, %d total)", loaded, len(_loaded_skills))
