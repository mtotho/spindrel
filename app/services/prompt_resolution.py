"""Resolve prompt template content — supports workspace file sources."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PromptTemplate

logger = logging.getLogger(__name__)


async def resolve_prompt_template(
    template_id: str | None,
    fallback: str,
    db: AsyncSession,
) -> str:
    """Return resolved content for a prompt template, or *fallback* if unlinked/missing.

    For ``source_type='workspace_file'`` templates the content is read live from
    the workspace filesystem.  The cached ``content`` / ``content_hash`` columns
    are updated transparently when the file changes.
    """
    if template_id is None:
        return fallback

    try:
        from uuid import UUID
        tid = UUID(str(template_id))
    except (ValueError, TypeError):
        return fallback

    row = await db.get(PromptTemplate, tid)
    if not row:
        return fallback

    if row.source_type == "workspace_file" and row.workspace_id and row.source_path:
        try:
            from app.services.shared_workspace import shared_workspace_service

            result = shared_workspace_service.read_file(
                str(row.workspace_id), row.source_path
            )
            content = result["content"]

            # Update cache if the file has changed
            new_hash = hashlib.sha256(content.encode()).hexdigest()
            if row.content_hash != new_hash:
                row.content = content
                row.content_hash = new_hash
                row.updated_at = datetime.now(timezone.utc)
                await db.commit()

            return content
        except Exception:
            logger.warning(
                "Failed to read workspace file for template %s — using cached content",
                template_id,
                exc_info=True,
            )
            return row.content or fallback

    return row.content or fallback
