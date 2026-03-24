"""API v1 — Shared Workspaces CRUD + container controls."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.bots import list_bots, reload_bots
from app.db.models import SharedWorkspace, SharedWorkspaceBot
from app.dependencies import get_db, verify_auth_or_user
from app.services.shared_workspace import shared_workspace_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workspaces", tags=["workspaces"])


# ── Pydantic schemas ────────────────────────────────────────────

class WorkspaceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    image: str = "agent-workspace:latest"
    network: str = "none"
    env: dict = {}
    ports: list = []
    mounts: list = []
    cpus: Optional[float] = None
    memory_limit: Optional[str] = None
    docker_user: Optional[str] = None
    read_only_root: bool = False
    created_by_user_id: Optional[str] = None


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    image: Optional[str] = None
    network: Optional[str] = None
    env: Optional[dict] = None
    ports: Optional[list] = None
    mounts: Optional[list] = None
    cpus: Optional[float] = None
    memory_limit: Optional[str] = None
    docker_user: Optional[str] = None
    read_only_root: Optional[bool] = None


class WorkspaceOut(BaseModel):
    id: str
    name: str
    description: Optional[str]
    image: str
    network: str
    env: dict
    ports: list
    mounts: list
    cpus: Optional[float]
    memory_limit: Optional[str]
    docker_user: Optional[str]
    read_only_root: bool
    container_id: Optional[str]
    container_name: Optional[str]
    status: str
    image_id: Optional[str]
    last_started_at: Optional[str]
    created_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    bots: list[dict] = []

    model_config = {"from_attributes": True}


class WorkspaceBotAdd(BaseModel):
    bot_id: str
    role: str = "member"
    cwd_override: Optional[str] = None


class WorkspaceBotUpdate(BaseModel):
    role: Optional[str] = None
    cwd_override: Optional[str] = None


# ── Helpers ─────────────────────────────────────────────────────

def _ws_to_out(ws: SharedWorkspace, sw_bots: list[SharedWorkspaceBot] | None = None) -> WorkspaceOut:
    bots = []
    if sw_bots:
        bot_map = {b.id: b for b in list_bots()}
        for swb in sw_bots:
            bot = bot_map.get(swb.bot_id)
            bots.append({
                "bot_id": swb.bot_id,
                "bot_name": bot.name if bot else swb.bot_id,
                "role": swb.role,
                "cwd_override": swb.cwd_override,
                "user_id": bot.user_id if bot else None,
            })
    return WorkspaceOut(
        id=str(ws.id),
        name=ws.name,
        description=ws.description,
        image=ws.image,
        network=ws.network,
        env=ws.env or {},
        ports=ws.ports or [],
        mounts=ws.mounts or [],
        cpus=ws.cpus,
        memory_limit=ws.memory_limit,
        docker_user=ws.docker_user,
        read_only_root=ws.read_only_root,
        container_id=ws.container_id,
        container_name=ws.container_name,
        status=ws.status,
        image_id=ws.image_id,
        last_started_at=ws.last_started_at.isoformat() if ws.last_started_at else None,
        created_by_user_id=str(ws.created_by_user_id) if ws.created_by_user_id else None,
        created_at=ws.created_at.isoformat(),
        updated_at=ws.updated_at.isoformat(),
        bots=bots,
    )


# ── CRUD ────────────────────────────────────────────────────────

@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    workspaces = (await db.execute(
        select(SharedWorkspace).order_by(SharedWorkspace.name)
    )).scalars().all()
    sw_bots = (await db.execute(select(SharedWorkspaceBot))).scalars().all()
    bots_by_ws = {}
    for swb in sw_bots:
        bots_by_ws.setdefault(swb.workspace_id, []).append(swb)
    return [_ws_to_out(ws, bots_by_ws.get(ws.id, [])) for ws in workspaces]


@router.post("", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    now = datetime.now(timezone.utc)
    ws = SharedWorkspace(
        name=body.name.strip(),
        description=body.description,
        image=body.image,
        network=body.network,
        env={k: v for k, v in body.env.items() if k},
        ports=body.ports,
        mounts=body.mounts,
        cpus=body.cpus,
        memory_limit=body.memory_limit,
        docker_user=body.docker_user,
        read_only_root=body.read_only_root,
        created_by_user_id=uuid.UUID(body.created_by_user_id) if body.created_by_user_id else None,
        created_at=now,
        updated_at=now,
    )
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    shared_workspace_service.ensure_host_dirs(str(ws.id))
    return _ws_to_out(ws)


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    sw_bots = (await db.execute(
        select(SharedWorkspaceBot).where(SharedWorkspaceBot.workspace_id == ws_id)
    )).scalars().all()
    return _ws_to_out(ws, sw_bots)


@router.put("/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(
    workspace_id: str,
    body: WorkspaceUpdate,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    for field in ("name", "description", "image", "network", "env", "ports", "mounts",
                  "cpus", "memory_limit", "docker_user", "read_only_root"):
        val = getattr(body, field, None)
        if val is not None:
            if isinstance(val, str):
                val = val.strip()
            elif isinstance(val, dict) and field == "env":
                val = {k: v for k, v in val.items() if k}
            setattr(ws, field, val)
    ws.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(ws)
    sw_bots = (await db.execute(
        select(SharedWorkspaceBot).where(SharedWorkspaceBot.workspace_id == ws_id)
    )).scalars().all()
    return _ws_to_out(ws, sw_bots)


@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    if ws.container_name:
        try:
            await shared_workspace_service.stop(ws)
        except Exception:
            pass
    await db.execute(delete(SharedWorkspace).where(SharedWorkspace.id == ws_id))
    await db.commit()
    await reload_bots()


# ── Container controls ──────────────────────────────────────────

@router.post("/{workspace_id}/start", response_model=WorkspaceOut)
async def start_workspace(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    try:
        await shared_workspace_service.ensure_container(ws)
    except Exception as exc:
        raise HTTPException(500, f"Start failed: {exc}")
    await db.refresh(ws)
    sw_bots = (await db.execute(
        select(SharedWorkspaceBot).where(SharedWorkspaceBot.workspace_id == ws_id)
    )).scalars().all()
    return _ws_to_out(ws, sw_bots)


@router.post("/{workspace_id}/stop", response_model=WorkspaceOut)
async def stop_workspace(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    await shared_workspace_service.stop(ws)
    await db.refresh(ws)
    sw_bots = (await db.execute(
        select(SharedWorkspaceBot).where(SharedWorkspaceBot.workspace_id == ws_id)
    )).scalars().all()
    return _ws_to_out(ws, sw_bots)


@router.post("/{workspace_id}/recreate", response_model=WorkspaceOut)
async def recreate_workspace(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    try:
        await shared_workspace_service.recreate(ws)
    except Exception as exc:
        raise HTTPException(500, f"Recreate failed: {exc}")
    await db.refresh(ws)
    sw_bots = (await db.execute(
        select(SharedWorkspaceBot).where(SharedWorkspaceBot.workspace_id == ws_id)
    )).scalars().all()
    return _ws_to_out(ws, sw_bots)


@router.post("/{workspace_id}/pull")
async def pull_workspace_image(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    ok, output = await shared_workspace_service.pull_image(ws.image)
    return {"success": ok, "output": output}


@router.get("/{workspace_id}/status")
async def workspace_status(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404)
    status = await shared_workspace_service.inspect_status(ws)
    return {"status": status}


@router.get("/{workspace_id}/logs")
async def workspace_logs(
    workspace_id: str,
    tail: int = Query(300, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404)
    logs = await shared_workspace_service.get_logs(ws, tail=tail)
    return {"logs": logs}


# ── Bot management ──────────────────────────────────────────────

@router.post("/{workspace_id}/bots", response_model=WorkspaceOut, status_code=201)
async def add_bot_to_workspace(
    workspace_id: str,
    body: WorkspaceBotAdd,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    swb = SharedWorkspaceBot(
        workspace_id=ws_id,
        bot_id=body.bot_id,
        role=body.role,
        cwd_override=body.cwd_override,
    )
    db.add(swb)
    try:
        await db.commit()
    except Exception as exc:
        raise HTTPException(400, f"Failed to add bot: {exc}")
    shared_workspace_service.ensure_bot_dir(str(ws_id), body.bot_id)
    await reload_bots()
    await db.refresh(ws)
    sw_bots = (await db.execute(
        select(SharedWorkspaceBot).where(SharedWorkspaceBot.workspace_id == ws_id)
    )).scalars().all()
    return _ws_to_out(ws, sw_bots)


@router.put("/{workspace_id}/bots/{bot_id}")
async def update_workspace_bot(
    workspace_id: str,
    bot_id: str,
    body: WorkspaceBotUpdate,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws_id = uuid.UUID(workspace_id)
    swb = (await db.execute(
        select(SharedWorkspaceBot).where(
            SharedWorkspaceBot.workspace_id == ws_id,
            SharedWorkspaceBot.bot_id == bot_id,
        )
    )).scalar_one_or_none()
    if not swb:
        raise HTTPException(404, "Bot not in workspace")
    if body.role is not None:
        swb.role = body.role
    if body.cwd_override is not None:
        swb.cwd_override = body.cwd_override or None
    await db.commit()
    await reload_bots()
    return {"bot_id": bot_id, "role": swb.role, "cwd_override": swb.cwd_override}


@router.delete("/{workspace_id}/bots/{bot_id}", status_code=204)
async def remove_bot_from_workspace(
    workspace_id: str,
    bot_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws_id = uuid.UUID(workspace_id)
    result = await db.execute(
        delete(SharedWorkspaceBot).where(
            SharedWorkspaceBot.workspace_id == ws_id,
            SharedWorkspaceBot.bot_id == bot_id,
        )
    )
    if result.rowcount == 0:
        raise HTTPException(404, "Bot not in workspace")
    await db.commit()
    await reload_bots()


# ── File browser ────────────────────────────────────────────────

@router.get("/{workspace_id}/files")
async def workspace_files(
    workspace_id: str,
    path: str = Query("/", description="Directory path inside the workspace"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404)
    entries = shared_workspace_service.list_files(workspace_id, path)
    return {"path": path, "entries": entries}


# ── Reindex ─────────────────────────────────────────────────────

@router.post("/{workspace_id}/reindex")
async def reindex_workspace(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404)
    sw_bots = (await db.execute(
        select(SharedWorkspaceBot).where(SharedWorkspaceBot.workspace_id == ws_id)
    )).scalars().all()

    from app.agent.fs_indexer import index_directory
    from app.services.workspace import workspace_service

    results = {}
    for swb in sw_bots:
        try:
            bot = next((b for b in list_bots() if b.id == swb.bot_id), None)
            if bot and bot.workspace.indexing.enabled:
                root = workspace_service.get_workspace_root(swb.bot_id, bot=bot)
                stats = await index_directory(root, swb.bot_id, bot.workspace.indexing.patterns, force=True)
                results[swb.bot_id] = stats
        except Exception as exc:
            results[swb.bot_id] = {"error": str(exc)}

    return {"results": results}
