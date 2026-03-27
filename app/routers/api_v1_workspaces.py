"""API v1 — Shared Workspaces CRUD + container controls."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, Form
from pydantic import BaseModel
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.bots import list_bots, reload_bots
from app.db.models import (
    Bot as BotRow,
    Channel, ChannelHeartbeat, ChannelIntegration, Message, PromptTemplate,
    Session, SharedWorkspace, SharedWorkspaceBot,
)
from app.dependencies import get_db, verify_auth_or_user
from app.services.shared_workspace import shared_workspace_service, SharedWorkspaceError

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
    startup_script: Optional[str] = "/workspace/startup.sh"
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
    startup_script: Optional[str] = None
    workspace_skills_enabled: Optional[bool] = None
    workspace_base_prompt_enabled: Optional[bool] = None
    indexing_config: Optional[dict] = None


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
    startup_script: Optional[str]
    workspace_skills_enabled: bool = True
    workspace_base_prompt_enabled: bool = True
    indexing_config: Optional[dict] = None
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
    # Workspace membership fields
    role: Optional[str] = None
    cwd_override: Optional[str] = None
    # Bot config fields (written to bots table)
    system_prompt: Optional[str] = None
    name: Optional[str] = None
    model: Optional[str] = None
    skills: Optional[list[dict]] = None
    local_tools: Optional[list[str]] = None
    persona: Optional[bool] = None
    persona_content: Optional[str] = None


class WorkspaceChannelOut(BaseModel):
    id: uuid.UUID
    name: str
    bot_id: str
    bot_name: Optional[str] = None
    display_name: Optional[str] = None
    integration: Optional[str] = None
    model_override: Optional[str] = None
    # Compaction
    compaction_prompt_template_id: Optional[uuid.UUID] = None
    compaction_prompt_template_name: Optional[str] = None
    memory_knowledge_compaction_prompt: Optional[str] = None
    # Heartbeat
    heartbeat_enabled: bool = False
    heartbeat_interval_minutes: int = 60
    heartbeat_prompt_template_id: Optional[uuid.UUID] = None
    heartbeat_prompt_template_name: Optional[str] = None
    heartbeat_prompt: Optional[str] = None
    # Activity
    last_user_turn_at: Optional[datetime] = None
    user_turns_24h: int = 0
    user_turns_48h: int = 0
    user_turns_72h: int = 0

    model_config = {"from_attributes": True}


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
                "indexing_enabled": bot.workspace.indexing.enabled if bot else False,
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
        startup_script=ws.startup_script,
        workspace_skills_enabled=ws.workspace_skills_enabled,
        workspace_base_prompt_enabled=ws.workspace_base_prompt_enabled,
        indexing_config=ws.indexing_config,
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
        startup_script=body.startup_script,
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


@router.api_route("/{workspace_id}", methods=["PUT", "PATCH"], response_model=WorkspaceOut)
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
    updates = body.model_dump(exclude_unset=True)
    for field, val in updates.items():
        if isinstance(val, str):
            val = val.strip()
        elif isinstance(val, dict) and field == "env":
            val = {k: v for k, v in val.items() if k}
        setattr(ws, field, val)
    ws.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(ws)
    # Refresh cached _ws_indexing_config on all bots when indexing config changes
    if "indexing_config" in updates:
        await reload_bots()
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


@router.get("/{workspace_id}/bots/{bot_id}")
async def get_workspace_bot(
    workspace_id: str,
    bot_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Get a bot's full config within a workspace context."""
    ws_id = uuid.UUID(workspace_id)
    swb = (await db.execute(
        select(SharedWorkspaceBot).where(
            SharedWorkspaceBot.workspace_id == ws_id,
            SharedWorkspaceBot.bot_id == bot_id,
        )
    )).scalar_one_or_none()
    if not swb:
        raise HTTPException(404, "Bot not in workspace")
    bot_row = await db.get(BotRow, bot_id)
    if not bot_row:
        raise HTTPException(404, "Bot not found")
    bot_map = {b.id: b for b in list_bots()}
    bot_cfg = bot_map.get(bot_id)

    from app.agent.persona import resolve_workspace_persona
    ws_persona = resolve_workspace_persona(workspace_id, bot_id)

    return {
        "bot_id": bot_id,
        "name": bot_row.name,
        "model": bot_row.model,
        "system_prompt": bot_row.system_prompt,
        "role": swb.role,
        "cwd_override": swb.cwd_override,
        "skills": bot_row.skills or [],
        "local_tools": bot_row.local_tools or [],
        "persona": bot_row.persona,
        "workspace": bot_row.workspace or {},
        "indexing_enabled": bot_cfg.workspace.indexing.enabled if bot_cfg else False,
        "persona_from_workspace": ws_persona is not None,
        "workspace_persona_content": ws_persona,
    }


@router.api_route("/{workspace_id}/bots/{bot_id}", methods=["PUT", "PATCH"])
async def update_workspace_bot(
    workspace_id: str,
    bot_id: str,
    body: WorkspaceBotUpdate,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Update a bot's workspace membership and/or config fields."""
    ws_id = uuid.UUID(workspace_id)
    swb = (await db.execute(
        select(SharedWorkspaceBot).where(
            SharedWorkspaceBot.workspace_id == ws_id,
            SharedWorkspaceBot.bot_id == bot_id,
        )
    )).scalar_one_or_none()
    if not swb:
        raise HTTPException(404, "Bot not in workspace")
    # Workspace membership fields
    updates = body.model_dump(exclude_unset=True)
    if "role" in updates:
        swb.role = updates["role"]
    if "cwd_override" in updates:
        swb.cwd_override = updates["cwd_override"] or None
    # Bot config fields (written to bots table)
    bot_fields = {
        k: v for k, v in updates.items()
        if k in {"system_prompt", "name", "model", "skills", "local_tools", "persona"}
    }
    if bot_fields:
        bot_row = await db.get(BotRow, bot_id)
        if not bot_row:
            raise HTTPException(404, "Bot not found")
        for key, val in bot_fields.items():
            setattr(bot_row, key, val)
        bot_row.updated_at = datetime.now(timezone.utc)
    # Handle persona_content separately (file-based)
    if body.persona_content is not None:
        from app.agent.persona import write_persona
        await write_persona(bot_id, body.persona_content)
    await db.commit()
    await reload_bots()
    return {"bot_id": bot_id, "role": swb.role, "cwd_override": swb.cwd_override, **bot_fields}


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


# ── Channels (batch-loaded) ─────────────────────────────────────

@router.get("/{workspace_id}/channels", response_model=list[WorkspaceChannelOut])
async def list_workspace_channels(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """List all channels for bots in this workspace, with inline heartbeat/compaction config."""
    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")

    # 1. Get workspace bot IDs
    sw_bots = (await db.execute(
        select(SharedWorkspaceBot.bot_id).where(SharedWorkspaceBot.workspace_id == ws_id)
    )).scalars().all()
    if not sw_bots:
        return []

    # 2. Channels with integrations eager-loaded
    channels = (await db.execute(
        select(Channel)
        .where(Channel.bot_id.in_(sw_bots))
        .options(selectinload(Channel.integrations))
        .order_by(Channel.name)
    )).scalars().all()
    if not channels:
        return []
    channel_ids = [ch.id for ch in channels]

    # 3. Heartbeats in batch
    heartbeats = (await db.execute(
        select(ChannelHeartbeat).where(ChannelHeartbeat.channel_id.in_(channel_ids))
    )).scalars().all()
    hb_map: dict[uuid.UUID, ChannelHeartbeat] = {hb.channel_id: hb for hb in heartbeats}

    # 4. Collect template IDs and batch-fetch names
    template_ids: set[uuid.UUID] = set()
    for ch in channels:
        if ch.compaction_prompt_template_id:
            template_ids.add(ch.compaction_prompt_template_id)
    for hb in heartbeats:
        if hb.prompt_template_id:
            template_ids.add(hb.prompt_template_id)

    tmpl_names: dict[uuid.UUID, str] = {}
    if template_ids:
        rows = (await db.execute(
            select(PromptTemplate.id, PromptTemplate.name)
            .where(PromptTemplate.id.in_(template_ids))
        )).all()
        tmpl_names = {r.id: r.name for r in rows}

    # 5. Activity stats (batched across all channels)
    now = datetime.now(timezone.utc)
    t24 = now - timedelta(hours=24)
    t48 = now - timedelta(hours=48)
    t72 = now - timedelta(hours=72)
    activity_q = (
        select(
            Session.channel_id,
            func.max(Message.created_at)
                .filter(Message.role == "user")
                .label("last_user_turn_at"),
            func.count()
                .filter(Message.role == "user", Message.created_at >= t24)
                .label("user_turns_24h"),
            func.count()
                .filter(Message.role == "user", Message.created_at >= t48)
                .label("user_turns_48h"),
            func.count()
                .filter(Message.role == "user", Message.created_at >= t72)
                .label("user_turns_72h"),
        )
        .select_from(Message)
        .join(Session, Message.session_id == Session.id)
        .where(Session.channel_id.in_(channel_ids))
        .group_by(Session.channel_id)
    )
    activity_rows = (await db.execute(activity_q)).all()
    activity_map: dict[uuid.UUID, dict] = {
        row.channel_id: {
            "last_user_turn_at": row.last_user_turn_at,
            "user_turns_24h": row.user_turns_24h,
            "user_turns_48h": row.user_turns_48h,
            "user_turns_72h": row.user_turns_72h,
        }
        for row in activity_rows
    }

    # 6. Bot names from in-memory registry
    bot_map = {b.id: b.name for b in list_bots()}

    # 7. Assemble
    out = []
    for ch in channels:
        hb = hb_map.get(ch.id)
        act = activity_map.get(ch.id, {})
        # First integration's display_name (if any)
        ci = ch.integrations[0] if ch.integrations else None
        out.append(WorkspaceChannelOut(
            id=ch.id,
            name=ch.name,
            bot_id=ch.bot_id,
            bot_name=bot_map.get(ch.bot_id, ch.bot_id),
            display_name=ci.display_name if ci else None,
            integration=ch.integration,
            model_override=ch.model_override,
            compaction_prompt_template_id=ch.compaction_prompt_template_id,
            compaction_prompt_template_name=tmpl_names.get(ch.compaction_prompt_template_id) if ch.compaction_prompt_template_id else None,
            memory_knowledge_compaction_prompt=ch.memory_knowledge_compaction_prompt,
            heartbeat_enabled=hb.enabled if hb else False,
            heartbeat_interval_minutes=hb.interval_minutes if hb else 60,
            heartbeat_prompt_template_id=hb.prompt_template_id if hb else None,
            heartbeat_prompt_template_name=tmpl_names.get(hb.prompt_template_id) if hb and hb.prompt_template_id else None,
            heartbeat_prompt=hb.prompt if hb else None,
            last_user_turn_at=act.get("last_user_turn_at"),
            user_turns_24h=act.get("user_turns_24h", 0),
            user_turns_48h=act.get("user_turns_48h", 0),
            user_turns_72h=act.get("user_turns_72h", 0),
        ))
    return out


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


class FileWriteBody(BaseModel):
    content: str


@router.get("/{workspace_id}/files/content")
async def read_workspace_file(
    workspace_id: str,
    path: str = Query(..., description="File path inside the workspace"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404)
    try:
        return shared_workspace_service.read_file(workspace_id, path)
    except SharedWorkspaceError as exc:
        raise HTTPException(400, str(exc))
    except PermissionError:
        raise HTTPException(403, f"Permission denied: {path}")
    except OSError as exc:
        raise HTTPException(400, f"OS error: {exc}")


@router.put("/{workspace_id}/files/content")
async def write_workspace_file(
    workspace_id: str,
    body: FileWriteBody,
    path: str = Query(..., description="File path inside the workspace"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404)
    try:
        return shared_workspace_service.write_file(workspace_id, path, body.content)
    except SharedWorkspaceError as exc:
        raise HTTPException(400, str(exc))
    except PermissionError:
        raise HTTPException(403, f"Permission denied: {path}")
    except OSError as exc:
        raise HTTPException(400, f"OS error: {exc}")


@router.post("/{workspace_id}/files/mkdir")
async def mkdir_workspace(
    workspace_id: str,
    path: str = Query(..., description="Directory path to create"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404)
    try:
        return shared_workspace_service.mkdir(workspace_id, path)
    except SharedWorkspaceError as exc:
        raise HTTPException(400, str(exc))
    except PermissionError:
        raise HTTPException(403, f"Permission denied: {path}")
    except OSError as exc:
        raise HTTPException(400, f"OS error: {exc}")


@router.delete("/{workspace_id}/files")
async def delete_workspace_file(
    workspace_id: str,
    path: str = Query(..., description="File or directory path to delete"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404)
    try:
        return shared_workspace_service.delete_path(workspace_id, path)
    except SharedWorkspaceError as exc:
        raise HTTPException(400, str(exc))
    except PermissionError:
        raise HTTPException(403, f"Permission denied: {path}")
    except OSError as exc:
        raise HTTPException(400, f"OS error: {exc}")


# ── File upload ─────────────────────────────────────────────────

@router.post("/{workspace_id}/files/upload")
async def upload_workspace_file(
    workspace_id: str,
    file: UploadFile = File(...),
    target_dir: str = Form("/"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404)
    content = await file.read()
    filename = file.filename or "upload"
    path = f"{target_dir.rstrip('/')}/{filename}"
    try:
        return shared_workspace_service.write_binary_file(workspace_id, path, content)
    except SharedWorkspaceError as exc:
        raise HTTPException(400, str(exc))
    except PermissionError:
        raise HTTPException(403, f"Permission denied: {path}")
    except OSError as exc:
        raise HTTPException(400, f"OS error: {exc}")


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
    from app.services.workspace_indexing import resolve_indexing, get_all_roots

    results = {}
    for swb in sw_bots:
        try:
            bot = next((b for b in list_bots() if b.id == swb.bot_id), None)
            if bot and bot.workspace.indexing.enabled:
                _resolved = resolve_indexing(bot.workspace.indexing, bot._workspace_raw, ws.indexing_config)
                bot_results = []
                for root in get_all_roots(bot):
                    stats = await index_directory(
                        root, swb.bot_id, _resolved["patterns"], force=True,
                        embedding_model=_resolved["embedding_model"],
                        segments=_resolved.get("segments"),
                    )
                    bot_results.append(stats)
                results[swb.bot_id] = bot_results[0] if len(bot_results) == 1 else bot_results
        except Exception as exc:
            results[swb.bot_id] = {"error": str(exc)}

    return {"results": results}


@router.post("/{workspace_id}/reindex-skills")
async def reindex_workspace_skills(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Re-discover and re-embed workspace skill .md files."""
    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")

    from app.services.workspace_skills import embed_workspace_skills
    stats = await embed_workspace_skills(workspace_id)
    return stats


@router.get("/{workspace_id}/skills")
async def list_workspace_skills(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """List discovered workspace skill files with metadata."""
    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")

    from app.services.workspace_skills import list_workspace_skill_files
    skills = await list_workspace_skill_files(workspace_id)
    return {"skills": skills}


# ── Indexing visibility + per-bot override ────────────────────────

class IndexSegmentUpdate(BaseModel):
    """Per-path-prefix config overrides within a bot's indexing config."""
    path_prefix: str
    embedding_model: Optional[str] = None
    patterns: Optional[list[str]] = None
    similarity_threshold: Optional[float] = None
    top_k: Optional[int] = None
    watch: Optional[bool] = None


class BotIndexingUpdate(BaseModel):
    """Per-bot indexing override. Send null for a field to clear it (inherit from workspace/global)."""
    enabled: Optional[bool] = None
    patterns: Optional[list[str]] = None
    similarity_threshold: Optional[float] = None
    top_k: Optional[int] = None
    watch: Optional[bool] = None
    cooldown_seconds: Optional[int] = None
    include_bots: Optional[list[str]] = None
    embedding_model: Optional[str] = None
    segments: Optional[list[IndexSegmentUpdate]] = None


@router.get("/{workspace_id}/indexing")
async def get_workspace_indexing(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Full indexing visibility: global defaults, workspace defaults, and per-bot resolved config."""
    from app.agent.fs_indexer import _SKIP_EXTENSIONS, _SKIP_DIRS
    from app.config import settings
    from app.services.workspace_indexing import resolve_indexing

    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    sw_bots = (await db.execute(
        select(SharedWorkspaceBot).where(SharedWorkspaceBot.workspace_id == ws_id)
    )).scalars().all()

    bot_map = {b.id: b for b in list_bots()}

    global_defaults = {
        "patterns": ["**/*.py", "**/*.md", "**/*.yaml"],
        "similarity_threshold": settings.FS_INDEX_SIMILARITY_THRESHOLD,
        "top_k": settings.FS_INDEX_TOP_K,
        "watch": True,
        "cooldown_seconds": settings.FS_INDEX_COOLDOWN_SECONDS,
        "embedding_model": settings.EMBEDDING_MODEL,
    }

    bots_out = []
    for swb in sw_bots:
        bot = bot_map.get(swb.bot_id)
        if not bot:
            continue
        raw_idx = bot._workspace_raw.get("indexing", {})
        # Detect which keys were explicitly set on the bot
        explicit = {}
        for key in ("patterns", "similarity_threshold", "top_k", "watch", "cooldown_seconds", "enabled", "include_bots", "embedding_model", "segments"):
            if key in raw_idx:
                explicit[key] = raw_idx[key]
        resolved = resolve_indexing(bot.workspace.indexing, bot._workspace_raw, ws.indexing_config)
        resolved["enabled"] = bot.workspace.indexing.enabled
        bots_out.append({
            "bot_id": swb.bot_id,
            "bot_name": bot.name,
            "role": swb.role,
            "indexing_enabled": bot.workspace.indexing.enabled,
            "explicit_overrides": explicit,
            "resolved": resolved,
        })

    supported_languages = [
        "python (.py) — AST-based chunking",
        "markdown (.md) — header-based chunking",
        "yaml (.yaml/.yml) — key-based chunking",
        "json (.json) — key-based chunking",
        "typescript (.ts/.tsx) — symbol-based chunking",
        "javascript (.js/.jsx) — symbol-based chunking",
        "go (.go) — function-based chunking",
        "rust (.rs) — function-based chunking",
        "other — sliding-window chunking",
    ]

    return {
        "global_defaults": global_defaults,
        "workspace_defaults": ws.indexing_config,
        "bots": bots_out,
        "supported_languages": supported_languages,
        "skip_extensions": sorted(_SKIP_EXTENSIONS),
        "skip_directories": sorted(_SKIP_DIRS),
    }


@router.api_route("/{workspace_id}/bots/{bot_id}/indexing", methods=["PUT", "PATCH"])
async def update_bot_indexing(
    workspace_id: str,
    bot_id: str,
    body: BotIndexingUpdate,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(verify_auth_or_user),
):
    """Update per-bot indexing overrides within a workspace. Send null to clear a field (inherit)."""
    from app.db.models import Bot as BotRow

    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")

    # Verify bot belongs to workspace
    swb = await db.get(SharedWorkspaceBot, (ws_id, bot_id))
    if not swb:
        raise HTTPException(404, f"Bot '{bot_id}' not in workspace")

    bot_row = await db.get(BotRow, bot_id)
    if not bot_row:
        raise HTTPException(404, f"Bot '{bot_id}' not found")

    ws_jsonb = dict(bot_row.workspace or {})
    indexing = dict(ws_jsonb.get("indexing", {}))

    # Merge: set provided fields, remove null fields (inherit)
    updates = body.model_dump(exclude_unset=True)
    for key, val in updates.items():
        if val is None:
            indexing.pop(key, None)
        elif key == "segments" and isinstance(val, list):
            # Serialize segment Pydantic models to dicts
            indexing[key] = [
                {k: v for k, v in seg.items() if v is not None} if isinstance(seg, dict) else seg
                for seg in val
            ]
        else:
            indexing[key] = val

    ws_jsonb["indexing"] = indexing
    bot_row.workspace = ws_jsonb
    await db.commit()
    await reload_bots()

    # Return resolved config for this bot
    from app.services.workspace_indexing import resolve_indexing
    bot = next((b for b in list_bots() if b.id == bot_id), None)
    resolved = {}
    if bot:
        resolved = resolve_indexing(bot.workspace.indexing, bot._workspace_raw, ws.indexing_config)
        resolved["enabled"] = bot.workspace.indexing.enabled

    return {
        "bot_id": bot_id,
        "explicit_overrides": indexing,
        "resolved": resolved,
    }
