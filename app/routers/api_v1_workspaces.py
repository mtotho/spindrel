"""API v1 — Shared Workspaces CRUD + container controls."""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, Form, Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.bots import list_bots, reload_bots
from app.db.models import (
    Bot as BotRow,
    Channel, ChannelHeartbeat, ChannelIntegration, Message, PromptTemplate,
    Session, SharedWorkspace, SharedWorkspaceBot,
)
from app.dependencies import get_db, require_scopes, verify_auth_or_user
from app.services.shared_workspace import shared_workspace_service, SharedWorkspaceError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workspaces", tags=["workspaces"])


# ── Background re-index after file mutations ───────────────────
# All functions use content-hash checks so they're cheap no-ops
# when nothing actually changed.

_MEMORY_PATH_SEGMENTS = ("memory/",)


def _path_touches(path: str, segments: tuple[str, ...]) -> bool:
    """Check if a path (or either side of a move) touches a segment."""
    return any(seg in path for seg in segments)


def _schedule_reindex_for_paths(workspace_id: str, *paths: str) -> None:
    """Fire-and-forget background re-index for affected subsystems.

    Inspects the paths to decide which indexes need refreshing:
    - memory/  → index_memory_for_bot (all bots in this workspace)
    - anything → index_directory for filesystem chunks (all bots)
    """
    touches_memory = any(_path_touches(p, _MEMORY_PATH_SEGMENTS) for p in paths)

    # Always reindex filesystem chunks — the file watcher might not catch
    # UI-driven mutations since they happen on the host path directly.
    asyncio.create_task(_background_reindex(
        workspace_id,
        reindex_memory=touches_memory,
        reindex_filesystem=True,
    ))


async def _background_reindex(
    workspace_id: str,
    *,
    reindex_memory: bool = False,
    reindex_filesystem: bool = False,
) -> None:
    """Run the appropriate re-index passes in the background."""
    try:
        if reindex_memory or reindex_filesystem:
            from app.db.engine import async_session
            from app.services.workspace_indexing import resolve_indexing, get_all_roots
            from app.services.workspace import workspace_service
            from app.services.memory_indexing import index_memory_for_bot
            from app.agent.fs_indexer import index_directory

            async with async_session() as db:
                sw_bots = (await db.execute(
                    select(SharedWorkspaceBot.bot_id)
                    .where(SharedWorkspaceBot.workspace_id == uuid.UUID(workspace_id))
                )).scalars().all()
                ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))

            for bot_id in sw_bots:
                bot = next((b for b in list_bots() if b.id == bot_id), None)
                if not bot or not bot.workspace.enabled:
                    continue

                if reindex_memory and bot.memory_scheme == "workspace-files":
                    try:
                        await index_memory_for_bot(bot, force=True)
                    except Exception:
                        logger.exception("Auto reindex memory failed for bot %s", bot_id)

                if reindex_filesystem and bot.workspace.indexing.enabled and ws:
                    try:
                        _resolved = resolve_indexing(
                            bot.workspace.indexing, bot._workspace_raw,
                            ws.indexing_config if ws else None,
                        )
                        _segments = _resolved.get("segments")
                        if not _segments:
                            continue
                        for root in get_all_roots(bot, workspace_service):
                            await index_directory(
                                root, bot_id, _resolved["patterns"],
                                embedding_model=_resolved["embedding_model"],
                                segments=_segments,
                            )
                    except Exception:
                        logger.exception("Auto reindex fs failed for bot %s", bot_id)
    except Exception:
        logger.exception("Background reindex failed for workspace %s", workspace_id[:8])


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
    write_protected_paths: list[str] = []


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
    workspace_base_prompt_enabled: Optional[bool] = None
    indexing_config: Optional[dict] = None
    write_protected_paths: Optional[list[str]] = None


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
    workspace_base_prompt_enabled: bool = True
    indexing_config: Optional[dict] = None
    editor_enabled: bool = False
    editor_port: Optional[int] = None
    write_protected_paths: list[str] = []
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


class WorkspaceBotUpdate(BaseModel):
    # Workspace membership fields
    role: Optional[str] = None
    cwd_override: Optional[str] = None
    write_access: Optional[list[str]] = None
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
                "write_access": swb.write_access or [],
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
        workspace_base_prompt_enabled=ws.workspace_base_prompt_enabled,
        indexing_config=ws.indexing_config,
        editor_enabled=ws.editor_enabled,
        editor_port=ws.editor_port,
        write_protected_paths=ws.write_protected_paths or [],
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


# ── Disk usage ──────────────────────────────────────────────────

@router.get("/disk-usage")
async def workspace_disk_usage(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces:read")),
):
    """Workspace disk usage report (bot-accessible with workspaces:read)."""
    from app.services.disk_usage import get_full_disk_report

    report = await get_full_disk_report()

    # Enrich with workspace names from DB
    ws_rows = (await db.execute(select(SharedWorkspace))).scalars().all()
    ws_names = {str(r.id): r.name for r in ws_rows}
    for ws in report["workspaces"]:
        if ws["type"] == "shared" and ws["id"] in ws_names:
            ws["name"] = ws_names[ws["id"]]

    return report


# ── CRUD ────────────────────────────────────────────────────────

@router.get("", response_model=list[WorkspaceOut])
async def list_workspaces(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces:read")),
):
    workspaces = (await db.execute(
        select(SharedWorkspace).order_by(SharedWorkspace.name)
    )).scalars().all()
    sw_bots = (await db.execute(select(SharedWorkspaceBot))).scalars().all()
    bots_by_ws = {}
    for swb in sw_bots:
        bots_by_ws.setdefault(swb.workspace_id, []).append(swb)
    return [_ws_to_out(ws, bots_by_ws.get(ws.id, [])) for ws in workspaces]


@router.get("/default", response_model=WorkspaceOut)
async def get_default_workspace(
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces:read")),
):
    """Convenience endpoint: return the single default workspace."""
    ws = (await db.execute(
        select(SharedWorkspace).order_by(SharedWorkspace.created_at.asc()).limit(1)
    )).scalar_one_or_none()
    if not ws:
        raise HTTPException(404, "No workspace exists")
    sw_bots = (await db.execute(
        select(SharedWorkspaceBot).where(SharedWorkspaceBot.workspace_id == ws.id)
    )).scalars().all()
    return _ws_to_out(ws, sw_bots)


@router.post("", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces:write")),
):
    # Single workspace mode: block creation if one already exists
    existing = (await db.execute(select(SharedWorkspace.id).limit(1))).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "Single workspace mode: a workspace already exists.")
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
        write_protected_paths=body.write_protected_paths,
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
    _auth=Depends(require_scopes("workspaces:read")),
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
    _auth=Depends(require_scopes("workspaces:write")),
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
    _auth=Depends(require_scopes("workspaces:write")),
):
    raise HTTPException(400, "Single workspace mode: the default workspace cannot be deleted.")


# ── Container controls ──────────────────────────────────────────

@router.post("/{workspace_id}/start", response_model=WorkspaceOut)
async def start_workspace(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces:write")),
):
    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    try:
        await shared_workspace_service.ensure_container(ws)
    except Exception as exc:
        logger.exception("Workspace start failed for %s", workspace_id)
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
    _auth=Depends(require_scopes("workspaces:write")),
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
    _auth=Depends(require_scopes("workspaces:write")),
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
    _auth=Depends(require_scopes("workspaces:write")),
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
    _auth=Depends(require_scopes("workspaces:read")),
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
    _auth=Depends(require_scopes("workspaces:read")),
):
    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404)
    logs = await shared_workspace_service.get_logs(ws, tail=tail)
    return {"logs": logs}


# ── Cron Jobs ─────────────────────────────────────────────────

@router.get("/{workspace_id}/cron-jobs")
async def workspace_cron_jobs(
    workspace_id: str,
    _auth=Depends(require_scopes("workspaces:read")),
):
    """Discover cron jobs inside a workspace container."""
    from app.services.cron_discovery import discover_crons
    from dataclasses import asdict

    result = await discover_crons(workspace_id=workspace_id)
    return {
        "cron_jobs": [asdict(e) for e in result.cron_jobs],
        "errors": result.errors,
    }


# ── Code Editor ────────────────────────────────────────────────

@router.post("/{workspace_id}/editor/enable")
async def enable_workspace_editor(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces:write")),
):
    """Enable and start code-server for this workspace."""
    from app.services.workspace_editor import ensure_editor
    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404, "Workspace not found")
    result = await ensure_editor(ws)
    await db.refresh(ws)
    return result


@router.post("/{workspace_id}/editor/disable")
async def disable_workspace_editor(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces:write")),
):
    """Disable code-server for this workspace."""
    from app.services.workspace_editor import disable_editor
    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404, "Workspace not found")
    await disable_editor(ws)
    return {"editor_enabled": False}


@router.get("/{workspace_id}/editor/status")
async def workspace_editor_status(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces:read")),
):
    """Get code-server status for this workspace."""
    from app.services.workspace_editor import editor_status
    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404, "Workspace not found")
    return await editor_status(ws)


@router.post("/{workspace_id}/editor/session")
async def create_editor_session(
    workspace_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces:read")),
):
    """Set an httpOnly session cookie for code-server access (new-tab loads)."""
    from fastapi.responses import JSONResponse

    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404, "Workspace not found")
    if not ws.editor_enabled:
        raise HTTPException(400, "Editor not enabled")

    # Extract the bearer token that was used to authenticate this request
    auth_header = request.headers.get("authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(400, "No token available for session")

    cookie_name = f"editor_session_{workspace_id.replace('-', '_')}"
    cookie_path = f"/api/v1/workspaces/{workspace_id}/editor"

    response = JSONResponse({"ok": True})
    response.set_cookie(
        key=cookie_name,
        value=token,
        path=cookie_path,
        httponly=True,
        samesite="lax",
        max_age=3600,  # 1 hour
    )
    return response


# ── Bot management ──────────────────────────────────────────────

@router.post("/{workspace_id}/bots", status_code=410)
async def add_bot_to_workspace(
    workspace_id: str,
    _auth=Depends(require_scopes("workspaces:write")),
):
    """Retired in single-workspace mode.

    Bots are auto-enrolled into the default workspace by the bootstrap loop
    (`ensure_all_bots_enrolled` in `app/services/workspace_bootstrap.py`)
    and stay there for their lifetime. Membership is owned by the server,
    not by the API.
    """
    raise HTTPException(
        status_code=410,
        detail="Single-workspace mode: bots are permanent members of the default workspace. Membership is managed by the server bootstrap loop.",
    )


@router.get("/{workspace_id}/bots/{bot_id}")
async def get_workspace_bot(
    workspace_id: str,
    bot_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces:read")),
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
        "write_access": swb.write_access or [],
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
    _auth=Depends(require_scopes("workspaces:write")),
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
    if "write_access" in updates:
        swb.write_access = updates["write_access"] or []
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
    return {"bot_id": bot_id, "role": swb.role, "cwd_override": swb.cwd_override, "write_access": swb.write_access or [], **bot_fields}


@router.delete("/{workspace_id}/bots/{bot_id}", status_code=410)
async def remove_bot_from_workspace(
    workspace_id: str,
    bot_id: str,
    _auth=Depends(require_scopes("workspaces:write")),
):
    """Retired in single-workspace mode.

    See `add_bot_to_workspace` — membership is owned by the bootstrap loop
    and any deletion would be reverted on next server start.
    """
    raise HTTPException(
        status_code=410,
        detail="Single-workspace mode: bots are permanent members of the default workspace. Membership is managed by the server bootstrap loop.",
    )


# ── Channels (batch-loaded) ─────────────────────────────────────

@router.get("/{workspace_id}/channels", response_model=list[WorkspaceChannelOut])
async def list_workspace_channels(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces:read")),
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

    # 2. Channels with integrations eager-loaded (include member channels)
    from app.db.models import ChannelBotMember
    channels = (await db.execute(
        select(Channel)
        .where(or_(
            Channel.bot_id.in_(sw_bots),
            Channel.id.in_(
                select(ChannelBotMember.channel_id).where(ChannelBotMember.bot_id.in_(sw_bots))
            ),
        ))
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
    _auth=Depends(require_scopes("workspaces.files:read")),
):
    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404)
    entries = shared_workspace_service.list_files(workspace_id, path)
    return {"path": path, "entries": entries}


class FileMoveBody(BaseModel):
    src: str
    dst: str


class FileWriteBody(BaseModel):
    content: str


@router.get("/{workspace_id}/files/content")
async def read_workspace_file(
    workspace_id: str,
    path: str = Query(..., description="File path inside the workspace"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces.files:read")),
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


_RAW_MIME_MAP = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
    ".ico": "image/x-icon", ".bmp": "image/bmp", ".pdf": "application/pdf",
}


@router.get("/{workspace_id}/files/raw")
async def read_workspace_file_raw(
    workspace_id: str,
    path: str = Query(..., description="File path inside the workspace"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces.files:read")),
):
    """Serve a workspace file as raw bytes (for images, PDFs, etc.)."""
    import os as _os
    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404)
    try:
        data = shared_workspace_service.read_file_bytes(workspace_id, path)
    except SharedWorkspaceError as exc:
        raise HTTPException(404, str(exc))
    except PermissionError:
        raise HTTPException(403, f"Permission denied: {path}")
    except OSError as exc:
        raise HTTPException(400, f"OS error: {exc}")
    ext = _os.path.splitext(path)[1].lower()
    mime = _RAW_MIME_MAP.get(ext, "application/octet-stream")
    return Response(content=data, media_type=mime, headers={"Cache-Control": "private, max-age=300"})


@router.put("/{workspace_id}/files/content")
async def write_workspace_file(
    workspace_id: str,
    body: FileWriteBody,
    path: str = Query(..., description="File path inside the workspace"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces.files:write")),
):
    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404)
    try:
        result = shared_workspace_service.write_file(workspace_id, path, body.content)
        _schedule_reindex_for_paths(workspace_id, path)
        return result
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
    _auth=Depends(require_scopes("workspaces.files:write")),
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
    _auth=Depends(require_scopes("workspaces.files:write")),
):
    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404)
    try:
        result = shared_workspace_service.delete_path(workspace_id, path)
        _schedule_reindex_for_paths(workspace_id, path)
        return result
    except SharedWorkspaceError as exc:
        raise HTTPException(400, str(exc))
    except PermissionError as exc:
        logger.warning("Filesystem permission error deleting %s: %s", path, exc)
        raise HTTPException(500, f"Filesystem permission denied: {path} (file may be owned by another process)")
    except OSError as exc:
        raise HTTPException(400, f"OS error: {exc}")


@router.post("/{workspace_id}/files/move")
async def move_workspace_file(
    workspace_id: str,
    body: FileMoveBody,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces.files:write")),
):
    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404)
    try:
        result = shared_workspace_service.move_path(workspace_id, body.src, body.dst)
        _schedule_reindex_for_paths(workspace_id, body.src, body.dst)
        return result
    except SharedWorkspaceError as exc:
        raise HTTPException(400, str(exc))
    except PermissionError:
        raise HTTPException(403, f"Permission denied")
    except OSError as exc:
        raise HTTPException(400, f"OS error: {exc}")


# ── File upload ─────────────────────────────────────────────────

@router.post("/{workspace_id}/files/upload")
async def upload_workspace_file(
    workspace_id: str,
    file: UploadFile = File(...),
    target_dir: str = Form("/"),
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces.files:write")),
):
    ws = await db.get(SharedWorkspace, uuid.UUID(workspace_id))
    if not ws:
        raise HTTPException(404)
    content = await file.read()
    filename = file.filename or "upload"
    path = f"{target_dir.rstrip('/')}/{filename}"
    try:
        result = shared_workspace_service.write_binary_file(workspace_id, path, content)
        _schedule_reindex_for_paths(workspace_id, path)
        return result
    except SharedWorkspaceError as exc:
        raise HTTPException(400, str(exc))
    except PermissionError:
        raise HTTPException(403, f"Permission denied: {path}")
    except OSError as exc:
        raise HTTPException(400, f"OS error: {exc}")


# ── Reindex ─────────────────────────────────────────────────────

@router.get("/{workspace_id}/files/index-status")
async def workspace_index_status(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces.files:read")),
):
    """Return which files are indexed by the RAG system, with chunk counts and metadata."""
    import os
    from app.db.models import FilesystemChunk

    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404)

    sw_bots = (await db.execute(
        select(SharedWorkspaceBot.bot_id).where(SharedWorkspaceBot.workspace_id == ws_id)
    )).scalars().all()
    if not sw_bots:
        return {"indexed_files": {}}

    host_root = os.path.realpath(shared_workspace_service.get_host_root(workspace_id))

    # Query: group by (root, file_path, bot_id) to get chunk counts + metadata
    rows = (await db.execute(
        select(
            FilesystemChunk.root,
            FilesystemChunk.file_path,
            FilesystemChunk.bot_id,
            func.count().label("chunk_count"),
            func.max(FilesystemChunk.indexed_at).label("last_indexed"),
            func.max(FilesystemChunk.language).label("language"),
            func.max(FilesystemChunk.embedding_model).label("embedding_model"),
        )
        .where(FilesystemChunk.bot_id.in_(sw_bots))
        .group_by(FilesystemChunk.root, FilesystemChunk.file_path, FilesystemChunk.bot_id)
    )).all()

    bot_map = {b.id: b.name for b in list_bots()}
    indexed: dict[str, dict] = {}

    for row in rows:
        # Build absolute path and make it relative to workspace host_root
        abs_path = os.path.join(row.root, row.file_path)
        real_abs = os.path.realpath(abs_path)
        if not real_abs.startswith(host_root):
            continue  # skip files outside this workspace
        rel_path = os.path.relpath(real_abs, host_root)

        # Determine source: memory if path starts with memory/ or bots/*/memory/
        parts = rel_path.split("/")
        if parts[0] == "memory" or (len(parts) >= 3 and parts[0] == "bots" and parts[2] == "memory"):
            source = "memory"
        else:
            source = "patterns"

        if rel_path not in indexed:
            indexed[rel_path] = {
                "chunk_count": 0,
                "last_indexed": None,
                "bots": [],
                "language": row.language,
                "embedding_model": row.embedding_model,
                "source": source,
            }
        entry = indexed[rel_path]
        entry["chunk_count"] += row.chunk_count
        ts = row.last_indexed.isoformat() if row.last_indexed else None
        if ts and (entry["last_indexed"] is None or ts > entry["last_indexed"]):
            entry["last_indexed"] = ts
        entry["bots"].append({
            "bot_id": row.bot_id,
            "bot_name": bot_map.get(row.bot_id, row.bot_id),
        })

    return {"indexed_files": indexed}


@router.post("/{workspace_id}/reindex")
async def reindex_workspace(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("workspaces:write")),
):
    ws_id = uuid.UUID(workspace_id)
    ws = await db.get(SharedWorkspace, ws_id)
    if not ws:
        raise HTTPException(404)
    sw_bots = (await db.execute(
        select(SharedWorkspaceBot).where(SharedWorkspaceBot.workspace_id == ws_id)
    )).scalars().all()

    from app.agent.fs_indexer import index_directory, cleanup_stale_roots
    from app.services.workspace_indexing import resolve_indexing, get_all_roots

    from app.services.memory_indexing import index_memory_for_bot

    results = {}

    # Phase 0: Clean up chunks from stale roots (e.g. after root path changes)
    for swb in sw_bots:
        bot = next((b for b in list_bots() if b.id == swb.bot_id), None)
        if bot and bot.workspace.enabled:
            try:
                valid = get_all_roots(bot)
                removed = await cleanup_stale_roots(bot.id, valid)
                if removed:
                    results.setdefault(swb.bot_id, {})["stale_roots_cleaned"] = removed
            except Exception:
                pass  # non-fatal

    # Phase 1: Memory reindex for all workspace-files bots
    memory_indexed_bot_ids: set[str] = set()
    for swb in sw_bots:
        bot = next((b for b in list_bots() if b.id == swb.bot_id), None)
        if bot and bot.memory_scheme == "workspace-files" and bot.workspace.enabled:
            try:
                stats = await index_memory_for_bot(bot, force=True)
                if stats:
                    results.setdefault(swb.bot_id, {}).update({"memory": stats})
                memory_indexed_bot_ids.add(swb.bot_id)
            except Exception as exc:
                results.setdefault(swb.bot_id, {})["memory_error"] = str(exc)

    # Phase 2: Segment-based indexing (only for bots with segments)
    for swb in sw_bots:
        try:
            bot = next((b for b in list_bots() if b.id == swb.bot_id), None)
            if bot and bot.workspace.indexing.enabled:
                _resolved = resolve_indexing(bot.workspace.indexing, bot._workspace_raw, ws.indexing_config)
                _segments = _resolved.get("segments")
                if not _segments:
                    continue
                bot_results = []
                for root in get_all_roots(bot):
                    stats = await index_directory(
                        root, swb.bot_id, _resolved["patterns"], force=True,
                        embedding_model=_resolved["embedding_model"],
                        segments=_segments,
                    )
                    bot_results.append(stats)
                results.setdefault(swb.bot_id, {})["indexing"] = bot_results[0] if len(bot_results) == 1 else bot_results
        except Exception as exc:
            results.setdefault(swb.bot_id, {})["indexing_error"] = str(exc)

    return {"results": results}


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
    _auth=Depends(require_scopes("workspaces:read")),
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
            "memory_scheme": getattr(bot, "memory_scheme", None),
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
    _auth=Depends(require_scopes("workspaces:write")),
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
