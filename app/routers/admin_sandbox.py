"""Admin routes for Docker sandbox management."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

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
    return RedirectResponse("/admin/sandboxes", status_code=303)


@router.post("/sandboxes/profiles/{profile_id}/edit", response_class=HTMLResponse)
async def admin_sandbox_edit_profile(
    profile_id: uuid.UUID,
    description: str = Form(""),
    image: str = Form(...),
    scope_mode: str = Form("session"),
    network_mode: str = Form("none"),
    idle_ttl_seconds: str = Form(""),
):
    ttl = int(idle_ttl_seconds) if idle_ttl_seconds.strip() else None
    async with async_session() as db:
        profile = await db.get(SandboxProfile, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        profile.description = description.strip() or None
        profile.image = image.strip()
        profile.scope_mode = scope_mode
        profile.network_mode = network_mode
        profile.idle_ttl_seconds = ttl
        await db.commit()
    return RedirectResponse("/admin/sandboxes", status_code=303)


@router.delete("/sandboxes/profiles/{profile_id}", response_class=HTMLResponse)
async def admin_sandbox_delete_profile(profile_id: uuid.UUID):
    async with async_session() as db:
        profile = await db.get(SandboxProfile, profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        await db.delete(profile)
        await db.commit()
    return HTMLResponse("", status_code=200)


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

        # Correlated tool calls — match on profile_name in arguments JSON + scope
        stmt = (
            select(ToolCall)
            .where(ToolCall.tool_name.in_(_SANDBOX_TOOL_NAMES))
            .where(ToolCall.arguments["profile_name"].astext == profile_name)
            .order_by(ToolCall.created_at.desc())
            .limit(100)
        )
        # Narrow to scope if session-scoped
        if inst.scope_type == "session":
            try:
                scope_session_id = uuid.UUID(inst.scope_key)
                stmt = stmt.where(ToolCall.session_id == scope_session_id)
            except ValueError:
                pass
        elif inst.scope_type == "bot":
            stmt = stmt.where(ToolCall.bot_id == inst.scope_key)

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
