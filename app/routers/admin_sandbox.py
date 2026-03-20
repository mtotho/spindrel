"""Admin routes for Docker sandbox management."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, or_, select

from app.agent.bots import list_bots
from app.config import settings
from app.db.engine import async_session
from app.db.models import SandboxBotAccess, SandboxInstance, SandboxProfile, ToolCall
from app.routers.admin_template_filters import install_admin_template_filters
from app.services.sandbox import sandbox_service

_SANDBOX_TOOL_NAMES = {"exec_sandbox", "ensure_sandbox", "stop_sandbox", "remove_sandbox", "list_sandbox_profiles"}

router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
install_admin_template_filters(templates.env)


def _ago(dt: datetime | None) -> str:
    if dt is None:
        return "never"
    now = datetime.now(timezone.utc)
    d = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    secs = int((now - d).total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


templates.env.filters["ago"] = _ago  # type: ignore[attr-defined]


async def _docker_live_status(container_id: str | None, container_name: str) -> str:
    """Return live Docker state string; fast path skipped when sandbox disabled."""
    if not settings.DOCKER_SANDBOX_ENABLED:
        return "disabled"
    identifier = container_id or container_name
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "inspect", "--format", "{{.State.Status}}", identifier,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode == 0:
            return stdout.decode().strip() or "unknown"
        return "not_found"
    except asyncio.TimeoutError:
        return "timeout"
    except Exception:
        return "error"


# ---------------------------------------------------------------------------
# Main sandbox page
# ---------------------------------------------------------------------------

@router.get("/sandboxes", response_class=HTMLResponse)
async def admin_sandboxes(request: Request):
    async with async_session() as db:
        # All profiles
        profiles_raw = list((await db.execute(
            select(SandboxProfile).order_by(SandboxProfile.name)
        )).scalars().all())

        # Bot access rows keyed by profile_id
        access_rows = list((await db.execute(select(SandboxBotAccess))).scalars().all())
        access_by_profile: dict[uuid.UUID, list[str]] = {}
        for row in access_rows:
            access_by_profile.setdefault(row.profile_id, []).append(row.bot_id)

        # All instances with profile name
        instances_raw = list((await db.execute(
            select(SandboxInstance).order_by(SandboxInstance.created_at.desc())
        )).scalars().all())

        profile_names = {p.id: p.name for p in profiles_raw}

    # Live Docker status for all instances (concurrent)
    live_statuses = await asyncio.gather(*[
        _docker_live_status(inst.container_id, inst.container_name)
        for inst in instances_raw
    ])

    profiles = [
        {
            "profile": p,
            "bot_access": sorted(access_by_profile.get(p.id, [])),
        }
        for p in profiles_raw
    ]

    instances = [
        {
            "instance": inst,
            "profile_name": profile_names.get(inst.profile_id, "?"),
            "docker_status": live_statuses[i],
        }
        for i, inst in enumerate(instances_raw)
    ]

    bots = list_bots()

    return templates.TemplateResponse(
        "admin/sandbox.html",
        {
            "request": request,
            "profiles": profiles,
            "instances": instances,
            "bots": bots,
            "sandbox_enabled": settings.DOCKER_SANDBOX_ENABLED,
        },
    )


# ---------------------------------------------------------------------------
# Profile management
# ---------------------------------------------------------------------------

@router.post("/sandboxes/profiles", response_class=HTMLResponse)
async def admin_sandbox_create_profile(
    name: str = Form(...),
    description: str = Form(""),
    image: str = Form(...),
    scope_mode: str = Form("session"),
    network_mode: str = Form("none"),
    idle_ttl_seconds: str = Form(""),
):
    ttl = int(idle_ttl_seconds) if idle_ttl_seconds.strip() else None
    async with async_session() as db:
        profile = SandboxProfile(
            name=name.strip(),
            description=description.strip() or None,
            image=image.strip(),
            scope_mode=scope_mode,
            network_mode=network_mode,
            idle_ttl_seconds=ttl,
        )
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        profile_id = profile.id
    return RedirectResponse(f"/admin/sandboxes/profiles/{profile_id}/edit", status_code=303)


@router.get("/sandboxes/profiles/{profile_id}/edit", response_class=HTMLResponse)
async def admin_sandbox_edit_profile_page(request: Request, profile_id: uuid.UUID):
    async with async_session() as db:
        profile = await db.get(SandboxProfile, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
    return templates.TemplateResponse("admin/sandbox_profile_edit.html", {
        "request": request,
        "profile": profile,
    })


@router.post("/sandboxes/profiles/{profile_id}/edit", response_class=HTMLResponse)
async def admin_sandbox_edit_profile(
    profile_id: uuid.UUID,
    description: str = Form(""),
    image: str = Form(...),
    scope_mode: str = Form("session"),
    network_mode: str = Form("none"),
    idle_ttl_seconds: str = Form(""),
    read_only_root: str = Form("false"),
    cpu_limit: str = Form(""),
    memory_limit: str = Form(""),
    run_as_user: str = Form(""),
    env_json: str = Form("{}"),
    mount_specs_json: str = Form("[]"),
    port_mappings_json: str = Form("[]"),
):
    ttl = int(idle_ttl_seconds) if idle_ttl_seconds.strip() else None
    try:
        env = json.loads(env_json or "{}")
    except json.JSONDecodeError:
        env = {}
    try:
        mount_specs = json.loads(mount_specs_json or "[]")
    except json.JSONDecodeError:
        mount_specs = []
    try:
        port_mappings = json.loads(port_mappings_json or "[]")
    except json.JSONDecodeError:
        port_mappings = []

    create_options: dict = {}
    if cpu_limit.strip():
        try:
            create_options["cpus"] = float(cpu_limit.strip())
        except ValueError:
            pass
    if memory_limit.strip():
        create_options["memory"] = memory_limit.strip()
    if run_as_user.strip():
        create_options["user"] = run_as_user.strip()

    async with async_session() as db:
        profile = await db.get(SandboxProfile, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        profile.description = description.strip() or None
        profile.image = image.strip()
        profile.scope_mode = scope_mode
        profile.network_mode = network_mode
        profile.idle_ttl_seconds = ttl
        profile.read_only_root = (read_only_root.lower() == "true")
        profile.create_options = create_options
        profile.env = env
        profile.mount_specs = mount_specs
        profile.port_mappings = port_mappings
        profile.updated_at = datetime.now(timezone.utc)
        await db.commit()
    return RedirectResponse(f"/admin/sandboxes/profiles/{profile_id}/edit?saved=1", status_code=303)


@router.delete("/sandboxes/profiles/{profile_id}", response_class=HTMLResponse)
async def admin_sandbox_delete_profile(profile_id: uuid.UUID):
    async with async_session() as db:
        profile = await db.get(SandboxProfile, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        await db.delete(profile)
        await db.commit()
    return HTMLResponse("", status_code=200)


@router.post("/sandboxes/profiles/{profile_id}/toggle", response_class=HTMLResponse)
async def admin_sandbox_toggle_profile(profile_id: uuid.UUID):
    async with async_session() as db:
        profile = await db.get(SandboxProfile, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        profile.enabled = not profile.enabled
        await db.commit()
    return RedirectResponse("/admin/sandboxes", status_code=303)


# ---------------------------------------------------------------------------
# Bot access management
# ---------------------------------------------------------------------------

@router.post("/sandboxes/access", response_class=HTMLResponse)
async def admin_sandbox_grant_access(
    bot_id: str = Form(...),
    profile_id: str = Form(...),
):
    pid = uuid.UUID(profile_id)
    async with async_session() as db:
        existing = await db.get(SandboxBotAccess, (bot_id.strip(), pid))
        if not existing:
            db.add(SandboxBotAccess(bot_id=bot_id.strip(), profile_id=pid))
            await db.commit()
    return RedirectResponse("/admin/sandboxes", status_code=303)


@router.delete("/sandboxes/access/{bot_id}/{profile_id}", response_class=HTMLResponse)
async def admin_sandbox_revoke_access(bot_id: str, profile_id: uuid.UUID):
    async with async_session() as db:
        row = await db.get(SandboxBotAccess, (bot_id, profile_id))
        if not row:
            raise HTTPException(status_code=404, detail="Access row not found")
        await db.delete(row)
        await db.commit()
    return HTMLResponse("", status_code=200)


# ---------------------------------------------------------------------------
# Instance detail + logs
# ---------------------------------------------------------------------------

async def _docker_logs(container_id: str, tail: int = 300) -> str:
    if not settings.DOCKER_SANDBOX_ENABLED:
        return "(Docker sandbox disabled — cannot fetch logs)"
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "logs", "--tail", str(tail), "--timestamps", container_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merge stderr into stdout (docker logs goes to stderr)
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        text = stdout.decode("utf-8", errors="replace").strip()
        return text or "(no log output)"
    except asyncio.TimeoutError:
        return "(timed out fetching logs)"
    except Exception as e:
        return f"(error: {e})"


def _parse_tool_result(result_str: str | None) -> dict:
    if not result_str:
        return {}
    try:
        return json.loads(result_str)
    except Exception:
        return {"raw": result_str}


@router.get("/sandboxes/instances/{instance_id}", response_class=HTMLResponse)
async def admin_sandbox_instance_detail(request: Request, instance_id: uuid.UUID):
    async with async_session() as db:
        inst = await db.get(SandboxInstance, instance_id)
        if not inst:
            return HTMLResponse("<div class='text-red-400 p-4'>Instance not found.</div>", status_code=404)

        profile = await db.get(SandboxProfile, inst.profile_id)
        profile_name = profile.name if profile else "?"

        # Correlated tool calls:
        # - exec/stop/remove: matched precisely by instance_id in arguments
        # - ensure_sandbox: matched by profile_name + bot + ±10s window around instance creation
        #   (ensure_sandbox args only contain profile_name, not the resulting instance_id)
        instance_id_str = str(inst.id)
        created_window_start = (inst.created_at - timedelta(seconds=10)) if inst.created_at else None
        created_window_end = (inst.created_at + timedelta(seconds=10)) if inst.created_at else None

        ensure_filters = [
            ToolCall.tool_name == "ensure_sandbox",
            ToolCall.arguments["profile_name"].astext == profile_name,
            ToolCall.bot_id == inst.created_by_bot,
        ]
        if created_window_start and created_window_end:
            ensure_filters += [
                ToolCall.created_at >= created_window_start,
                ToolCall.created_at <= created_window_end,
            ]

        stmt = (
            select(ToolCall)
            .where(
                or_(
                    and_(
                        ToolCall.tool_name.in_({"exec_sandbox", "stop_sandbox", "remove_sandbox"}),
                        ToolCall.arguments["instance_id"].astext == instance_id_str,
                    ),
                    and_(*ensure_filters),
                )
            )
            .order_by(ToolCall.created_at.desc())
            .limit(100)
        )

        tool_calls_raw = list((await db.execute(stmt)).scalars().all())
    # Annotate tool calls with parsed result
    tool_calls = [
        {
            "tc": tc,
            "parsed_result": _parse_tool_result(tc.result),
            "command": (tc.arguments or {}).get("command"),
        }
        for tc in tool_calls_raw
    ]

    # Fetch Docker logs
    logs = await _docker_logs(inst.container_id) if inst.container_id else "(no container ID yet)"
    docker_status = await _docker_live_status(inst.container_id, inst.container_name)

    return templates.TemplateResponse(
        "admin/sandbox_instance.html",
        {
            "request": request,
            "inst": inst,
            "profile_name": profile_name,
            "tool_calls": tool_calls,
            "logs": logs,
            "docker_status": docker_status,
            "sandbox_enabled": settings.DOCKER_SANDBOX_ENABLED,
        },
    )


@router.get("/sandboxes/instances/{instance_id}/logs", response_class=HTMLResponse)
async def admin_sandbox_instance_logs(instance_id: uuid.UUID, tail: int = 300):
    """HTMX partial — returns just the log pre block for refresh."""
    async with async_session() as db:
        inst = await db.get(SandboxInstance, instance_id)
        if not inst or not inst.container_id:
            return HTMLResponse("<pre class='text-gray-500 text-xs'>No container.</pre>")
    logs = await _docker_logs(inst.container_id, tail=tail)
    escaped = logs.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return HTMLResponse(
        f'<pre id="log-output" class="text-xs text-gray-300 font-mono whitespace-pre-wrap break-all">{escaped}</pre>'
    )


# ---------------------------------------------------------------------------
# Instance controls (admin bypasses locked_operations)
# ---------------------------------------------------------------------------

@router.post("/sandboxes/instances/{instance_id}/stop", response_class=HTMLResponse)
async def admin_sandbox_stop(request: Request, instance_id: uuid.UUID):
    async with async_session() as db:
        inst = await db.get(SandboxInstance, instance_id)
        if not inst:
            raise HTTPException(status_code=404, detail="Instance not found")
        container_id = inst.container_id

    if container_id:
        await sandbox_service._docker_stop(container_id)

    async with async_session() as db:
        inst = await db.get(SandboxInstance, instance_id)
        if inst:
            inst.status = "stopped"
            inst.last_inspected_at = datetime.now(timezone.utc)
            await db.commit()

    if request.headers.get("X-Requested-With") == "fetch":
        return HTMLResponse("", status_code=200)
    return RedirectResponse("/admin/sandboxes", status_code=303)


@router.post("/sandboxes/instances/{instance_id}/remove", response_class=HTMLResponse)
async def admin_sandbox_remove(request: Request, instance_id: uuid.UUID):
    async with async_session() as db:
        inst = await db.get(SandboxInstance, instance_id)
        if not inst:
            raise HTTPException(status_code=404, detail="Instance not found")
        container_id = inst.container_id

    if container_id:
        await sandbox_service._docker_stop(container_id)
        await sandbox_service._docker_rm(container_id)

    async with async_session() as db:
        inst = await db.get(SandboxInstance, instance_id)
        if inst:
            await db.delete(inst)
            await db.commit()

    if request.headers.get("X-Requested-With") == "fetch":
        return HTMLResponse("", status_code=200)
    return RedirectResponse("/admin/sandboxes", status_code=303)


@router.post("/sandboxes/instances/{instance_id}/lock", response_class=HTMLResponse)
async def admin_sandbox_set_lock(
    request: Request,
    instance_id: uuid.UUID,
    stop: Optional[str] = Form(None),
    remove: Optional[str] = Form(None),
    ensure: Optional[str] = Form(None),
    exec_: Optional[str] = Form(None, alias="exec"),
):
    locked = []
    if stop:
        locked.append("stop")
    if remove:
        locked.append("remove")
    if ensure:
        locked.append("ensure")
    if exec_:
        locked.append("exec")

    async with async_session() as db:
        inst = await db.get(SandboxInstance, instance_id)
        if not inst:
            raise HTTPException(status_code=404, detail="Instance not found")
        inst.locked_operations = locked
        await db.commit()

    return RedirectResponse("/admin/sandboxes", status_code=303)


@router.delete("/sandboxes/instances/{instance_id}/lock", response_class=HTMLResponse)
async def admin_sandbox_clear_lock(instance_id: uuid.UUID):
    async with async_session() as db:
        inst = await db.get(SandboxInstance, instance_id)
        if not inst:
            raise HTTPException(status_code=404, detail="Instance not found")
        inst.locked_operations = []
        await db.commit()
    return RedirectResponse("/admin/sandboxes", status_code=303)
