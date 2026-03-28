"""Indexing diagnostics: /diagnostics/indexing — shows health of all indexing systems."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import (
    Bot as BotRow,
    Document,
    FilesystemChunk,
    SharedWorkspace,
    SharedWorkspaceBot,
    Skill as SkillRow,
)
from app.dependencies import get_db, verify_auth_or_user

router = APIRouter()


@router.get("/diagnostics/indexing")
async def diagnostics_indexing(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
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
        "litellm_base_url": settings.LITELLM_BASE_URL,
        "error": embed_error,
    }

    # --- 2. File-sourced skills ---
    from app.services.file_sync import _collect_skill_files, _collect_knowledge_files
    skill_files = _collect_skill_files()
    knowledge_files = _collect_knowledge_files()
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
        "knowledge_files_on_disk": len(knowledge_files),
    }

    # --- 3. Workspace skills ---
    ws_rows = (await db.execute(select(SharedWorkspace))).scalars().all()
    ws_skills_info = []
    for ws in ws_rows:
        ws_doc_count = (await db.execute(
            select(func.count()).select_from(Document)
            .where(Document.source.like(f"workspace_skill:{ws.id}:%"))
        )).scalar_one()
        ws_distinct_sources = (await db.execute(
            select(func.count(func.distinct(Document.source)))
            .where(Document.source.like(f"workspace_skill:{ws.id}:%"))
        )).scalar_one()
        ws_skills_info.append({
            "workspace_id": str(ws.id),
            "workspace_name": ws.name,
            "skills_enabled": bool(ws.workspace_skills_enabled),
            "document_chunks": ws_doc_count,
            "distinct_skills": ws_distinct_sources,
        })
    result["systems"]["workspace_skills"] = ws_skills_info

    # --- 4. Filesystem indexing (per bot) ---
    from app.agent.bots import list_bots, get_bot
    from app.services.workspace import workspace_service
    from app.services.memory_scheme import get_memory_rel_path

    fs_info = []
    for bot in list_bots():
        if not (bot.workspace.enabled and bot.workspace.indexing.enabled):
            continue
        ws_root = workspace_service.get_workspace_root(bot.id, bot)
        ws_root_resolved = str(Path(ws_root).resolve())
        root_exists = os.path.isdir(ws_root_resolved)

        # Resolve the correct memory prefix for this bot
        # (orchestrators use "bots/{bot_id}/memory", members use "memory")
        mem_rel = get_memory_rel_path(bot)
        mem_prefix_pattern = mem_rel.rstrip("/") + "/%"

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

        # Count chunks in DB
        chunk_count = (await db.execute(
            select(func.count()).select_from(FilesystemChunk)
            .where(
                FilesystemChunk.bot_id == bot.id,
                FilesystemChunk.root == ws_root_resolved,
            )
        )).scalar_one()

        # Count memory-specific chunks (using bot-appropriate prefix)
        memory_chunk_count = (await db.execute(
            select(func.count()).select_from(FilesystemChunk)
            .where(
                FilesystemChunk.bot_id == bot.id,
                FilesystemChunk.root == ws_root_resolved,
                FilesystemChunk.file_path.like(mem_prefix_pattern),
            )
        )).scalar_one()

        # Count chunks with embeddings
        embedded_count = (await db.execute(
            select(func.count()).select_from(FilesystemChunk)
            .where(
                FilesystemChunk.bot_id == bot.id,
                FilesystemChunk.root == ws_root_resolved,
                FilesystemChunk.embedding.isnot(None),
            )
        )).scalar_one()

        # Count chunks with tsvector populated
        tsv_count = (await db.execute(
            select(func.count()).select_from(FilesystemChunk)
            .where(
                FilesystemChunk.bot_id == bot.id,
                FilesystemChunk.root == ws_root_resolved,
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
    if not ws_skills_info:
        issues.append("No shared workspaces configured")
    for ws in ws_skills_info:
        if ws["skills_enabled"] and ws["document_chunks"] == 0:
            issues.append(f"Workspace '{ws['workspace_name']}': skills enabled but 0 chunks indexed")

    result["issues"] = issues
    result["healthy"] = len(issues) == 0

    return result


@router.post("/diagnostics/reindex")
async def diagnostics_reindex(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Force re-index ALL filesystem directories and workspace skills."""
    from app.agent.bots import list_bots
    from app.agent.fs_indexer import index_directory
    from app.services.workspace import workspace_service
    from app.services.workspace_indexing import resolve_indexing, get_all_roots

    results = {"filesystem": [], "workspace_skills": []}

    # Re-index filesystem chunks
    from app.services.memory_indexing import index_memory_for_bot

    memory_indexed_bot_ids: set[str] = set()
    for bot in list_bots():
        if not (bot.workspace.enabled and bot.workspace.indexing.enabled):
            continue
        _resolved = resolve_indexing(
            bot.workspace.indexing, bot._workspace_raw, bot._ws_indexing_config
        )
        for root in get_all_roots(bot, workspace_service):
            try:
                stats = await index_directory(
                    root, bot.id, _resolved["patterns"], force=True,
                    embedding_model=_resolved["embedding_model"],
                    segments=_resolved.get("segments"),
                )
                results["filesystem"].append({
                    "bot_id": bot.id, "root": root, **stats,
                })
            except Exception as e:
                results["filesystem"].append({
                    "bot_id": bot.id, "root": root, "error": str(e),
                })
        if bot.memory_scheme == "workspace-files":
            memory_indexed_bot_ids.add(bot.id)

    # Memory-only reindex for bots with workspace-files but no general indexing
    for bot in list_bots():
        if (
            bot.memory_scheme == "workspace-files"
            and bot.workspace.enabled
            and bot.id not in memory_indexed_bot_ids
        ):
            try:
                stats = await index_memory_for_bot(bot, force=True)
                if stats:
                    results["filesystem"].append({
                        "bot_id": bot.id, "source": "memory-only", **stats,
                    })
            except Exception as e:
                results["filesystem"].append({
                    "bot_id": bot.id, "source": "memory-only", "error": str(e),
                })

    # Re-embed workspace skills
    from app.db.models import SharedWorkspace as SW
    ws_rows = (await db.execute(select(SW).where(SW.workspace_skills_enabled == True))).scalars().all()  # noqa: E712
    if ws_rows:
        from app.services.workspace_skills import embed_workspace_skills
        for ws in ws_rows:
            try:
                stats = await embed_workspace_skills(str(ws.id))
                results["workspace_skills"].append({
                    "workspace": ws.name, **stats,
                })
            except Exception as e:
                results["workspace_skills"].append({
                    "workspace": ws.name, "error": str(e),
                })

    return {"ok": True, **results}
