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


def resolve_workspace_file_prompt(
    workspace_id: str | None,
    file_path: str | None,
    fallback: str,
) -> str:
    """Read a workspace file directly and return its content, or *fallback* on failure."""
    if not workspace_id or not file_path:
        return fallback
    try:
        from app.services.shared_workspace import shared_workspace_service
        result = shared_workspace_service.read_file(workspace_id, file_path)
        return result["content"]
    except Exception:
        logger.warning(
            "Failed to read workspace file %s/%s — using fallback",
            workspace_id, file_path, exc_info=True,
        )
        return fallback


async def resolve_prompt(
    *,
    workspace_id: str | None = None,
    workspace_file_path: str | None = None,
    template_id: str | None = None,
    inline_prompt: str,
    db: AsyncSession,
) -> str:
    """Unified prompt resolution with priority: workspace_file > template > inline.

    Parameters
    ----------
    workspace_id:
        Shared workspace UUID string for direct file linking.
    workspace_file_path:
        Path within the workspace to read as the prompt.
    template_id:
        PromptTemplate UUID string (legacy path).
    inline_prompt:
        Fallback inline prompt text.
    db:
        Async DB session (needed for template resolution).
    """
    # 1. Direct workspace file takes highest priority
    if workspace_id and workspace_file_path:
        result = resolve_workspace_file_prompt(workspace_id, workspace_file_path, "")
        if result:
            return result

    # 2. Prompt template
    if template_id:
        result = await resolve_prompt_template(template_id, "", db)
        if result:
            return result

    # 3. Inline prompt
    return inline_prompt
