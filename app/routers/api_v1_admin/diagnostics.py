"""Indexing diagnostics: /diagnostics/indexing — shows health of all indexing systems."""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    Bot as BotRow,
    Document,
    FilesystemChunk,
    Session,
    SharedWorkspace,
    SharedWorkspaceBot,
    Skill as SkillRow,
)
from app.domain.errors import NotFoundError
from app.dependencies import get_db, require_scopes
from app.services.native_plan_fixtures import seed_native_plan_unsupported_adherence_fixture
from app.services.session_plan_mode import publish_session_plan_event

router = APIRouter()


class NativePlanUnsupportedFixtureRequest(BaseModel):
    session_id: uuid.UUID
    channel_id: uuid.UUID
    bot_id: str = Field(default="e2e-bot", min_length=1)
    variant: Literal["unsupported", "retry_recovered"] = "unsupported"
    marker: str | None = None


@router.get("/diagnostics/indexing")
async def diagnostics_indexing(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    """Comprehensive indexing health check across all systems."""
    result: dict = {"cwd": str(Path.cwd()), "systems": {}}

    # --- 1. Embedding health ---
    embed_ok = False
    embed_error = None
    try:
        from app.agent.embeddings import embed_text
        vec = await embed_text("diagnostic test")
        embed_ok = bool(vec and len(vec) > 0)
        if embed_ok:
            result["embedding_dimensions"] = len(vec)
    except Exception as e:
        embed_error = str(e)
    result["systems"]["embedding"] = {
        "healthy": embed_ok,
        "model": settings.EMBEDDING_MODEL,
        "llm_base_url": settings.LLM_BASE_URL,
        "error": embed_error,
    }

    # --- 2. File-sourced skills ---
    from app.services.file_sync import _collect_skill_files
    skill_files = _collect_skill_files()
    db_skill_count = (await db.execute(select(func.count()).select_from(SkillRow))).scalar_one()
    db_file_skills = (await db.execute(
        select(func.count()).select_from(SkillRow).where(SkillRow.source_type == "file")
    )).scalar_one()
    skill_doc_count = (await db.execute(
        select(func.count()).select_from(Document).where(Document.source.like("skill:%"))
    )).scalar_one()

    result["systems"]["file_skills"] = {
        "files_on_disk": len(skill_files),
        "files_detail": [{"path": str(p), "id": sid, "type": st} for p, sid, st in skill_files[:20]],
        "skills_in_db_total": db_skill_count,
        "skills_in_db_file_sourced": db_file_skills,
        "skill_document_chunks": skill_doc_count,
    }

    # --- 3. Filesystem indexing (per bot) ---
    from app.agent.bots import list_bots, get_bot
    from app.services.bot_indexing import resolve_for
    from app.services.memory_scheme import get_memory_rel_path, get_memory_index_prefix
    from app.services.workspace import workspace_service

    fs_info = []
    for bot in list_bots():
        if not (bot.workspace.enabled and bot.workspace.indexing.enabled):
            continue
        ws_root = workspace_service.get_workspace_root(bot.id, bot)
        ws_root_resolved = str(Path(ws_root).resolve())
        root_exists = os.path.isdir(ws_root_resolved)

        # Physical prefix for on-disk walks (relative to bot's own directory)
        mem_rel = get_memory_rel_path(bot)
        # Index prefix for DB queries (relative to indexing root = workspace root for shared)
        mem_index_prefix = get_memory_index_prefix(bot)
        mem_prefix_pattern = mem_index_prefix.rstrip("/") + "/%"

        # Build pathspec for gitignore filtering (same as indexer)
        from app.agent.fs_indexer import _build_pathspec
        spec = _build_pathspec(Path(ws_root_resolved))

        # Count files on disk
        file_count_on_disk = 0
        memory_files_on_disk = 0
        gitignore_excluded = 0
        memory_gitignore_excluded = 0
        if root_exists:
            for dirpath, dirnames, filenames in os.walk(ws_root_resolved):
                # Skip hidden and build dirs
                dirnames[:] = [d for d in dirnames if d not in {
                    ".git", "__pycache__", "node_modules", ".venv", "venv",
                }]
                for fn in filenames:
                    if fn.endswith((".py", ".md", ".yaml")):
                        rel = os.path.relpath(os.path.join(dirpath, fn), ws_root_resolved)
                        is_memory = rel.startswith(mem_rel + "/") or rel.startswith(mem_rel + os.sep)
                        # Check if gitignored
                        if spec and spec.match_file(rel.replace(os.sep, "/")):
                            gitignore_excluded += 1
                            if is_memory:
                                memory_gitignore_excluded += 1
                            continue
                        file_count_on_disk += 1
                        if is_memory:
                            memory_files_on_disk += 1

        # Use the indexing root (workspace root for shared ws bots) for DB queries
        _plan = resolve_for(bot, scope="workspace")
        _db_roots = [str(Path(r).resolve()) for r in (_plan.roots if _plan else [])]
        _root_filter = FilesystemChunk.root.in_(_db_roots)

        # Count chunks in DB
        chunk_count = (await db.execute(
            select(func.count()).select_from(FilesystemChunk)
            .where(
                FilesystemChunk.bot_id == bot.id,
                _root_filter,
            )
        )).scalar_one()

        # Count memory-specific chunks (using bot-appropriate prefix)
        memory_chunk_count = (await db.execute(
            select(func.count()).select_from(FilesystemChunk)
            .where(
                FilesystemChunk.bot_id == bot.id,
                _root_filter,
                FilesystemChunk.file_path.like(mem_prefix_pattern),
            )
        )).scalar_one()

        # Count chunks with embeddings
        embedded_count = (await db.execute(
            select(func.count()).select_from(FilesystemChunk)
            .where(
                FilesystemChunk.bot_id == bot.id,
                _root_filter,
                FilesystemChunk.embedding.isnot(None),
            )
        )).scalar_one()

        # Count chunks with tsvector populated
        tsv_count = (await db.execute(
            select(func.count()).select_from(FilesystemChunk)
            .where(
                FilesystemChunk.bot_id == bot.id,
                _root_filter,
                FilesystemChunk.tsv.isnot(None),
            )
        )).scalar_one()

        fs_info.append({
            "bot_id": bot.id,
            "workspace_root": ws_root_resolved,
            "root_exists": root_exists,
            "memory_rel_prefix": mem_rel,
            "files_on_disk": file_count_on_disk,
            "memory_files_on_disk": memory_files_on_disk,
            "gitignore_excluded": gitignore_excluded,
            "memory_gitignore_excluded": memory_gitignore_excluded,
            "has_gitignore": spec is not None,
            "chunks_in_db": chunk_count,
            "memory_chunks_in_db": memory_chunk_count,
            "chunks_with_embedding": embedded_count,
            "chunks_with_tsv": tsv_count,
            "shared_workspace_id": bot.shared_workspace_id,
            "shared_workspace_role": getattr(bot, "shared_workspace_role", None),
            "memory_scheme": getattr(bot, "memory_scheme", None),
        })

    result["systems"]["filesystem_indexing"] = fs_info

    # --- 5. Summary / health flags ---
    issues = []
    if not embed_ok:
        issues.append("CRITICAL: Embedding service is down — ALL indexing is broken")
    for fi in fs_info:
        if fi["root_exists"] and fi["files_on_disk"] > 0 and fi["chunks_in_db"] == 0:
            issues.append(f"Bot {fi['bot_id']}: {fi['files_on_disk']} files on disk but 0 chunks indexed")
        if fi["memory_files_on_disk"] > 0 and fi["memory_chunks_in_db"] == 0:
            issues.append(f"Bot {fi['bot_id']}: {fi['memory_files_on_disk']} memory files on disk but 0 memory chunks indexed")
        if fi["chunks_in_db"] > 0 and fi["chunks_with_embedding"] == 0:
            issues.append(f"Bot {fi['bot_id']}: {fi['chunks_in_db']} chunks but 0 have embeddings")
        if fi.get("memory_gitignore_excluded", 0) > 0:
            issues.append(
                f"Bot {fi['bot_id']}: {fi['memory_gitignore_excluded']} memory files excluded by .gitignore — "
                "these will NOT be indexed (check .gitignore rules)"
            )
        if not fi["root_exists"]:
            issues.append(f"Bot {fi['bot_id']}: workspace root does not exist: {fi['workspace_root']}")

    result["issues"] = issues
    result["healthy"] = len(issues) == 0

    return result


@router.get("/diagnostics/operations")
async def diagnostics_operations(
    _auth: str = Depends(require_scopes("admin")),
):
    """Return in-progress background operations (lightweight, no DB)."""
    from app.services import progress
    return {"operations": progress.list_operations()}


@router.post("/diagnostics/native-plan-fixtures/unsupported-adherence")
async def diagnostics_native_plan_unsupported_adherence_fixture(
    body: NativePlanUnsupportedFixtureRequest,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    """Seed a deterministic native plan adherence fixture for live parity tests."""
    session = await db.get(Session, body.session_id)
    if session is None:
        raise NotFoundError(f"Session not found: {body.session_id}")
    result = await seed_native_plan_unsupported_adherence_fixture(
        db,
        session,
        channel_id=body.channel_id,
        bot_id=body.bot_id,
        variant=body.variant,
        marker=body.marker,
    )
    await db.commit()
    publish_session_plan_event(session, "semantic_review")
    return result


@router.post("/diagnostics/reindex")
async def diagnostics_reindex(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    """Force re-index ALL filesystem directories."""
    from app.agent.bots import list_bots
    from app.services import progress
    from app.services.bot_indexing import reindex_bot

    reindex_op = progress.start("reindex", "Full reindex")
    results: dict = {"filesystem": []}

    try:
        bots = [
            b for b in list_bots()
            if b.workspace.enabled
            and (b.workspace.indexing.enabled or b.memory_scheme == "workspace-files")
        ]
        bot_count = len(bots)
        for i, bot in enumerate(bots, start=1):
            try:
                stats = await reindex_bot(bot, force=True, cleanup_orphans=True)
                if stats:
                    results["filesystem"].append({"bot_id": bot.id, **stats})
            except Exception as e:
                results["filesystem"].append({"bot_id": bot.id, "error": str(e)})
            progress.update(reindex_op, current=i, total=bot_count, message=f"Done {bot.id}")

        progress.complete(reindex_op, message="Reindex complete")
    except Exception as e:
        progress.fail(reindex_op, message=str(e))
        raise

    return {"ok": True, **results}


@router.get("/diagnostics/memory-search/{bot_id}")
async def diagnostics_memory_search(
    bot_id: str,
    query: str = "test",
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    """Test memory search for a specific bot — returns raw diagnostic data.

    Hit this endpoint to see exactly why search_memory returns empty.
    Example: GET /api/v1/admin/diagnostics/memory-search/dev_bot?query=user+preferences
    """
    from app.agent.bots import get_bot
    from app.services.bot_indexing import resolve_for
    from app.services.memory_scheme import get_memory_index_prefix
    from app.services.memory_search import hybrid_memory_search

    bot = get_bot(bot_id)
    if not bot:
        return {"error": f"Bot not found: {bot_id}"}
    if bot.memory_scheme != "workspace-files":
        return {"error": f"Bot {bot_id} does not use workspace-files memory scheme"}

    plan = resolve_for(bot, scope="workspace")
    if plan is None:
        return {"error": f"Bot {bot_id} has workspace disabled"}
    embedding_model = plan.embedding_model
    roots = [str(Path(r).resolve()) for r in plan.roots]
    memory_prefix = get_memory_index_prefix(bot)
    path_pattern = memory_prefix.rstrip("/") + "/%"

    # Run the search
    results = await hybrid_memory_search(
        query=query,
        bot_id=bot_id,
        roots=roots,
        memory_prefix=memory_prefix,
        embedding_model=embedding_model,
        top_k=10,
    )

    # Run diagnostic counts directly
    diag = {}
    try:
        root_placeholders = ", ".join(f":root_{i}" for i in range(len(roots)))
        root_params = {f"root_{i}": r for i, r in enumerate(roots)}
        diag_sql = text(f"""
            SELECT
                count(*) AS total_chunks,
                count(*) FILTER (WHERE bot_id = :bot_id) AS matching_bot,
                count(*) FILTER (WHERE bot_id = :bot_id AND root IN ({root_placeholders})) AS matching_root,
                count(*) FILTER (WHERE bot_id = :bot_id AND root IN ({root_placeholders}) AND file_path LIKE :path_pattern) AS matching_path,
                count(*) FILTER (WHERE bot_id = :bot_id AND root IN ({root_placeholders}) AND file_path LIKE :path_pattern AND embedding IS NOT NULL) AS with_embedding,
                count(*) FILTER (WHERE bot_id = :bot_id AND root IN ({root_placeholders}) AND file_path LIKE :path_pattern AND tsv IS NOT NULL) AS with_tsv
            FROM filesystem_chunks
        """)
        row = (await db.execute(diag_sql, {"bot_id": bot_id, "path_pattern": path_pattern, **root_params})).one()
        diag = {
            "total_chunks_in_table": row.total_chunks,
            "matching_bot_id": row.matching_bot,
            "matching_bot_and_root": row.matching_root,
            "matching_bot_root_path": row.matching_path,
            "with_embedding": row.with_embedding,
            "with_tsv": row.with_tsv,
        }

        # Also get distinct file_paths and embedding_models for this bot+root
        sample_sql = text(f"""
            SELECT DISTINCT file_path, embedding_model, root
            FROM filesystem_chunks
            WHERE bot_id = :bot_id AND root IN ({root_placeholders})
            ORDER BY file_path
            LIMIT 30
        """)
        sample_rows = (await db.execute(sample_sql, {"bot_id": bot_id, **root_params})).all()
        diag["sample_files"] = [
            {"file_path": r.file_path, "embedding_model": r.embedding_model, "root": r.root}
            for r in sample_rows
        ]

        # Get distinct roots for this bot (to catch root mismatches)
        roots_sql = text("SELECT DISTINCT root FROM filesystem_chunks WHERE bot_id = :bot_id")
        roots_rows = (await db.execute(roots_sql, {"bot_id": bot_id})).all()
        diag["all_roots_for_bot"] = [r.root for r in roots_rows]
    except Exception as e:
        diag["diagnostic_error"] = str(e)

    return {
        "bot_id": bot_id,
        "query": query,
        "embedding_model": embedding_model,
        "query_roots": roots,
        "memory_prefix": memory_prefix,
        "path_pattern": path_pattern,
        "result_count": len(results),
        "results": [
            {"file_path": r.file_path, "score": r.score, "content_preview": r.content[:200]}
            for r in results
        ],
        "diagnostics": diag,
    }


@router.get("/diagnostics/disk-usage")
async def diagnostics_disk_usage(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    """Workspace disk usage report."""
    from app.services.disk_usage import get_full_disk_report

    report = await get_full_disk_report()

    # Attachment storage stats (reuse the stats endpoint query)
    from app.routers.api_v1_admin.attachments import attachment_global_stats
    att_stats = await attachment_global_stats(db=db)
    report["attachments"] = {
        "total_count": att_stats.total_count,
        "with_file_data_count": att_stats.with_file_data_count,
        "total_size_bytes": att_stats.total_size_bytes,
    }

    # Enrich shared workspace entries with names from DB
    ws_rows = (await db.execute(select(SharedWorkspace))).scalars().all()
    ws_names = {str(r.id): r.name for r in ws_rows}

    for ws in report["workspaces"]:
        if ws["type"] == "shared" and ws["id"] in ws_names:
            ws["name"] = ws_names[ws["id"]]
        elif ws["type"] == "bot":
            # Try to match bot dir name to a shared workspace
            for row in ws_rows:
                if row.id and str(row.id) == ws["id"]:
                    ws["name"] = row.name
                    break

    return report


@router.get("/diagnostics/feature-validation")
async def diagnostics_feature_validation(
    _auth: str = Depends(require_scopes("admin")),
):
    """Validate that all bots have tools required by their configured features."""
    from app.services.feature_validation import validate_features

    warnings = await validate_features()
    return {
        "warnings": [w.to_dict() for w in warnings],
        "warning_count": len(warnings),
        "healthy": len(warnings) == 0,
    }
