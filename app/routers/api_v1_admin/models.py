"""Models + completions: /models, /completions."""
from __future__ import annotations

import asyncio
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot, Skill as SkillRow, ToolEmbedding
from app.dependencies import get_db, verify_auth_or_user

logger = logging.getLogger(__name__)
router = APIRouter()


class ModelOut(BaseModel):
    id: str
    display: str
    max_tokens: Optional[int] = None
    download_status: Optional[Literal["cached", "not_downloaded", "downloading"]] = None
    size_mb: Optional[int] = None


class ModelGroupOut(BaseModel):
    provider_id: Optional[str] = None
    provider_name: str
    provider_type: str
    models: list[ModelOut]


class DownloadRequest(BaseModel):
    model_id: str


class DownloadResponse(BaseModel):
    operation_id: str
    model_id: str


class CompletionItem(BaseModel):
    value: str
    label: str


@router.get("/models", response_model=list[ModelGroupOut])
async def admin_models(
    _auth: str = Depends(verify_auth_or_user),
):
    """List all available LLM models grouped by provider."""
    from app.services.providers import get_available_models_grouped
    try:
        groups = await get_available_models_grouped()
    except Exception:
        logger.exception("Failed to fetch model groups")
        groups = []
    return [
        ModelGroupOut(
            provider_id=g.get("provider_id"),
            provider_name=g["provider_name"],
            provider_type=g["provider_type"],
            models=[ModelOut(id=m["id"], display=m["display"], max_tokens=m.get("max_tokens")) for m in g["models"]],
        )
        for g in groups
    ]


@router.get("/embedding-models", response_model=list[ModelGroupOut])
async def admin_embedding_models(
    _auth: str = Depends(verify_auth_or_user),
):
    """List all available embedding models grouped by provider.

    Includes LiteLLM provider models plus local fastembed models (if available).
    """
    from app.agent.local_embeddings import list_local_models
    from app.services import progress
    from app.services.providers import get_available_models_grouped

    groups: list[ModelGroupOut] = []

    # LiteLLM providers (same as /models)
    try:
        llm_groups = await get_available_models_grouped()
    except Exception:
        logger.exception("Failed to fetch model groups for embedding models endpoint")
        llm_groups = []
    for g in llm_groups:
        groups.append(ModelGroupOut(
            provider_id=g.get("provider_id"),
            provider_name=g["provider_name"],
            provider_type=g["provider_type"],
            models=[ModelOut(id=m["id"], display=m["display"], max_tokens=m.get("max_tokens")) for m in g["models"]],
        ))

    # Local fastembed models
    local_models = list_local_models()
    if local_models:
        # Check active download operations to override status
        active_downloads: set[str] = set()
        for op in progress.list_operations():
            if op["type"] == "model_download" and op["status"] == "running":
                active_downloads.add(op.get("label", ""))

        models_out = []
        for m in local_models:
            status = m["download_status"]
            if m["id"] in active_downloads:
                status = "downloading"
            models_out.append(ModelOut(
                id=m["id"],
                display=f"{m['display']} ({m['dimensions']}d)",
                download_status=status,
                size_mb=m["size_mb"],
            ))

        groups.append(ModelGroupOut(
            provider_id=None,
            provider_name="Local (fastembed)",
            provider_type="local",
            models=models_out,
        ))

    return groups


@router.post("/embedding-models/download", response_model=DownloadResponse)
async def download_embedding_model(
    body: DownloadRequest,
    _auth: str = Depends(verify_auth_or_user),
):
    """Trigger download of a local fastembed embedding model."""
    from app.agent.local_embeddings import (
        KNOWN_MODELS,
        LOCAL_PREFIX,
        download_model_sync,
        is_local_model,
        strip_prefix,
    )
    from app.services import progress

    if not is_local_model(body.model_id):
        raise HTTPException(status_code=400, detail="Only local/ models can be downloaded")

    bare_name = strip_prefix(body.model_id)
    known_names = {name for name, _, _ in KNOWN_MODELS}
    if bare_name not in known_names:
        raise HTTPException(status_code=404, detail=f"Unknown local model: {bare_name}")

    # Check if already downloading
    for op in progress.list_operations():
        if op["type"] == "model_download" and op["label"] == body.model_id and op["status"] == "running":
            return DownloadResponse(operation_id=op["id"], model_id=body.model_id)

    op_id = progress.start("model_download", body.model_id)

    loop = asyncio.get_running_loop()

    async def _run_download() -> None:
        try:
            await loop.run_in_executor(None, download_model_sync, bare_name)
            progress.complete(op_id, message="Download complete")
        except Exception as exc:
            logger.exception("Failed to download model %s", bare_name)
            progress.fail(op_id, message=str(exc))

    asyncio.create_task(_run_download())

    return DownloadResponse(operation_id=op_id, model_id=body.model_id)


@router.get("/completions", response_model=list[CompletionItem])
async def admin_completions(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Get @-tag completions for skills, tools, tool-packs, and bots."""
    from app.tools.packs import get_tool_packs

    all_skills = (await db.execute(
        select(SkillRow).order_by(SkillRow.name)
    )).scalars().all()
    tool_names = (await db.execute(
        select(ToolEmbedding.tool_name).distinct().order_by(ToolEmbedding.tool_name)
    )).scalars().all()
    packs = get_tool_packs()
    all_bots = (await db.execute(
        select(Bot).order_by(Bot.name)
    )).scalars().all()

    items: list[CompletionItem] = []
    for b in all_bots:
        items.append(CompletionItem(value=f"bot:{b.id}", label=f"bot:{b.id} — {b.name}"))
    for s in all_skills:
        items.append(CompletionItem(value=f"skill:{s.id}", label=f"skill:{s.id} — {s.name}"))
    for t in tool_names:
        items.append(CompletionItem(value=f"tool:{t}", label=f"tool:{t}"))
    for k, v in sorted(packs.items()):
        items.append(CompletionItem(value=f"tool-pack:{k}", label=f"tool-pack:{k} — {len(v)} tools"))
    return items
