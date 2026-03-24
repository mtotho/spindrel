"""Models + completions: /models, /completions."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Skill as SkillRow, ToolEmbedding
from app.dependencies import get_db, verify_auth_or_user

router = APIRouter()


class ModelOut(BaseModel):
    id: str
    display: str
    max_tokens: Optional[int] = None


class ModelGroupOut(BaseModel):
    provider_id: Optional[str] = None
    provider_name: str
    provider_type: str
    models: list[ModelOut]


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


@router.get("/completions", response_model=list[CompletionItem])
async def admin_completions(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
):
    """Get @-tag completions for skills, tools, and tool-packs."""
    from app.tools.packs import get_tool_packs

    all_skills = (await db.execute(
        select(SkillRow).order_by(SkillRow.name)
    )).scalars().all()
    tool_names = (await db.execute(
        select(ToolEmbedding.tool_name).distinct().order_by(ToolEmbedding.tool_name)
    )).scalars().all()
    packs = get_tool_packs()

    items: list[CompletionItem] = []
    for s in all_skills:
        items.append(CompletionItem(value=f"skill:{s.id}", label=f"skill:{s.id} — {s.name}"))
    for t in tool_names:
        items.append(CompletionItem(value=f"tool:{t}", label=f"tool:{t}"))
    for k, v in sorted(packs.items()):
        items.append(CompletionItem(value=f"tool-pack:{k}", label=f"tool-pack:{k} — {len(v)} tools"))
    return items
