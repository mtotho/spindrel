"""Integration setup status, settings management, process control, and dependency management."""
from __future__ import annotations

import asyncio
import logging
import sys

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task
from app.dependencies import get_db
from app.services.integration_processes import process_manager

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_setup_vars(integration_id: str) -> list[dict]:
    """Load the SETUP env_vars list for an integration from its setup.py.

    Auto-injects a ``SIDEBAR_ENABLED`` setting for integrations that declare
    a ``sidebar_section`` in their SETUP, so admins can toggle sidebar visibility
    without any per-integration code.
    """
    from integrations import _iter_integration_candidates, _import_module

    for candidate, iid, is_external, source in _iter_integration_candidates():
        if iid != integration_id:
            continue
        setup_file = candidate / "setup.py"
        if not setup_file.exists():
            return []
        module = _import_module(iid, "setup", setup_file, is_external, source)
        setup = getattr(module, "SETUP", {})
        env_vars = list(setup.get("env_vars", []))

        # Auto-inject SIDEBAR_ENABLED for integrations with sidebar_section
        sidebar = setup.get("sidebar_section")
        if sidebar and isinstance(sidebar, dict) and sidebar.get("items"):
            existing_keys = {v["key"] for v in env_vars}
            if "SIDEBAR_ENABLED" not in existing_keys:
                env_vars.append({
                    "key": "SIDEBAR_ENABLED",
                    "required": False,
                    "type": "boolean",
                    "description": "Show this integration's sidebar section in the navigation",
                    "default": "true",
                })

        return env_vars
    return []


@router.get("/integrations")
async def list_integrations():
    from integrations import discover_setup_status

    base_url = ""
    try:
        from app.config import settings
        base_url = getattr(settings, "BASE_URL", "") or ""
    except Exception:
        pass

    return {"integrations": discover_setup_status(base_url)}


@router.get("/integrations/icons")
async def list_integration_icons():
    """Return a lightweight mapping of integration_id -> lucide icon name."""
    from integrations import discover_setup_status

    statuses = discover_setup_status()
    icons = {s["id"]: s.get("icon", "Plug") for s in statuses}
    return {"icons": icons}


@router.get("/integrations/sidebar-sections")
async def list_sidebar_sections():
    """Return sidebar sections declared by integrations via their SETUP manifests.

    Filters out sections whose integration has ``SIDEBAR_ENABLED`` set to ``"false"``.
    """
    from integrations import discover_sidebar_sections
    from app.services.integration_settings import get_value, is_disabled

    sections = discover_sidebar_sections()
    visible = []
    for section in sections:
        iid = section["integration_id"]
        if is_disabled(iid):
            continue
        enabled = get_value(iid, "SIDEBAR_ENABLED", "true")
        if enabled.lower() != "false":
            visible.append(section)
    return {"sections": visible}


# ---------------------------------------------------------------------------
# Global disable/enable
# ---------------------------------------------------------------------------


class DisabledBody(BaseModel):
    disabled: bool


@router.put("/integrations/{integration_id}/disabled")
async def set_integration_disabled(integration_id: str, body: DisabledBody):
    """Globally disable or enable an integration.

    Disabling: stops process, unregisters tools, removes embeddings.
    Enabling: reloads tools and re-indexes. Does NOT auto-start process.
    """
    from app.services.integration_settings import set_disabled, is_disabled

    already = is_disabled(integration_id)
    if body.disabled == already:
        return {"integration_id": integration_id, "disabled": already}

    if body.disabled:
        # 1) Persist flag
        await set_disabled(integration_id, True)
        # 2) Stop process if running
        try:
            await process_manager.stop(integration_id)
        except Exception:
            logger.debug("No process to stop for %s", integration_id, exc_info=True)
        # 3) Unregister tools from registry
        from app.tools.registry import unregister_integration_tools
        removed = unregister_integration_tools(integration_id)
        # 4) Remove embeddings
        from app.agent.tools import remove_integration_embeddings
        embed_count = await remove_integration_embeddings(integration_id)
        logger.info(
            "Disabled integration %s: removed %d tool(s), %d embedding(s)",
            integration_id, len(removed), embed_count,
        )
    else:
        # 1) Persist flag
        await set_disabled(integration_id, False)
        # 2) Reload tools from disk
        from integrations import _iter_integration_candidates
        from app.tools.loader import load_integration_tools
        loaded: list[str] = []
        for candidate, iid, _is_external, _source in _iter_integration_candidates():
            if iid == integration_id:
                loaded = load_integration_tools(candidate)
                break
        # 3) Re-index all local tools
        from app.agent.tools import index_local_tools
        await index_local_tools()
        logger.info(
            "Enabled integration %s: loaded %d tool(s)",
            integration_id, len(loaded),
        )

    return {"integration_id": integration_id, "disabled": body.disabled}


@router.get("/integrations/{integration_id}/settings")
async def get_integration_settings(integration_id: str):
    from app.services.integration_settings import get_all_for_integration

    setup_vars = _get_setup_vars(integration_id)
    settings = get_all_for_integration(integration_id, setup_vars)
    return {"settings": settings}


class UpdateSettingsBody(BaseModel):
    settings: dict[str, str]


@router.put("/integrations/{integration_id}/settings")
async def update_integration_settings(
    integration_id: str,
    body: UpdateSettingsBody,
    db: AsyncSession = Depends(get_db),
):
    from app.services.integration_settings import update_settings

    setup_vars = _get_setup_vars(integration_id)
    valid_keys = {v["key"] for v in setup_vars}
    bad_keys = set(body.settings.keys()) - valid_keys
    if bad_keys:
        raise HTTPException(status_code=422, detail=f"Unknown setting keys: {', '.join(sorted(bad_keys))}")

    applied = await update_settings(integration_id, body.settings, setup_vars, db)

    # Auto-provision API key if integration declares api_permissions and doesn't have one yet
    api_permissions = _get_api_permissions(integration_id)
    if api_permissions:
        from app.services.api_keys import get_integration_api_key as _get_key, provision_integration_api_key, resolve_scopes
        existing = await _get_key(db, integration_id)
        if not existing:
            try:
                scopes = resolve_scopes(api_permissions)
                await provision_integration_api_key(db, integration_id, scopes)
                logger.info("Auto-provisioned API key for integration %s", integration_id)
            except Exception:
                logger.warning("Failed to auto-provision API key for %s", integration_id, exc_info=True)

    return {"applied": applied}


@router.delete("/integrations/{integration_id}/settings/{key}")
async def delete_integration_setting(
    integration_id: str,
    key: str,
    db: AsyncSession = Depends(get_db),
):
    from app.services.integration_settings import delete_setting

    await delete_setting(integration_id, key, db)
    return {"deleted": key}


# ---------------------------------------------------------------------------
# Process control endpoints
# ---------------------------------------------------------------------------


@router.get("/integrations/{integration_id}/process")
async def get_process_status(integration_id: str):
    return process_manager.status(integration_id)


@router.post("/integrations/{integration_id}/process/start")
async def start_process(integration_id: str):
    from app.services.integration_settings import is_disabled
    if is_disabled(integration_id):
        raise HTTPException(status_code=400, detail="Integration is globally disabled")
    ok = await process_manager.start(integration_id)
    if not ok:
        status = process_manager.status(integration_id)
        if status["status"] == "running":
            raise HTTPException(status_code=409, detail="Process is already running")
        raise HTTPException(status_code=400, detail="Failed to start process (check env vars and logs)")
    return process_manager.status(integration_id)


@router.post("/integrations/{integration_id}/process/stop")
async def stop_process(integration_id: str):
    ok = await process_manager.stop(integration_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Process is not running")
    return process_manager.status(integration_id)


@router.post("/integrations/{integration_id}/process/restart")
async def restart_process(integration_id: str):
    ok = await process_manager.restart(integration_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to restart process")
    return process_manager.status(integration_id)


class AutoStartBody(BaseModel):
    enabled: bool


@router.put("/integrations/{integration_id}/process/auto-start")
async def set_auto_start(integration_id: str, body: AutoStartBody):
    await process_manager.set_auto_start(integration_id, body.enabled)
    return {"integration_id": integration_id, "auto_start": body.enabled}


@router.get("/integrations/{integration_id}/process/auto-start")
async def get_auto_start(integration_id: str):
    enabled = await process_manager.get_auto_start(integration_id)
    return {"integration_id": integration_id, "auto_start": enabled}


# ---------------------------------------------------------------------------
# Python dependency installation
# ---------------------------------------------------------------------------


@router.post("/integrations/{integration_id}/install-deps")
async def install_deps(integration_id: str):
    """Install Python dependencies from the integration's requirements.txt."""
    from integrations import _iter_integration_candidates

    # Find the integration directory
    req_path = None
    for candidate, iid, _is_external, _source in _iter_integration_candidates():
        if iid == integration_id:
            rp = candidate / "requirements.txt"
            if rp.exists():
                req_path = str(rp)
            break

    if req_path is None:
        raise HTTPException(status_code=404, detail=f"No requirements.txt found for integration {integration_id!r}")

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "-q", "-r", req_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            err = (stderr or stdout or b"").decode(errors="replace").strip()
            logger.error("pip install failed for %s: %s", integration_id, err)
            raise HTTPException(status_code=500, detail=f"pip install failed: {err[:500]}")

        logger.info("Installed dependencies for integration %s", integration_id)
        return {
            "integration_id": integration_id,
            "installed": True,
            "message": "Dependencies installed. Restart the server to activate new tools.",
        }

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="pip install timed out after 120s")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to install deps for %s", integration_id)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/integrations/{integration_id}/install-npm-deps")
async def install_npm_deps(integration_id: str):
    """Install npm dependencies declared in the integration's setup.py."""
    from integrations import _iter_integration_candidates, _import_module

    # Find the integration and read its SETUP
    npm_deps = None
    for candidate, iid, is_external, source in _iter_integration_candidates():
        if iid == integration_id:
            setup_file = candidate / "setup.py"
            if setup_file.exists():
                module = _import_module(iid, "setup", setup_file, is_external, source)
                setup = getattr(module, "SETUP", {})
                npm_deps = setup.get("npm_dependencies", [])
            break

    if not npm_deps:
        raise HTTPException(status_code=404, detail=f"No npm_dependencies found for integration {integration_id!r}")

    packages = [dep["package"] for dep in npm_deps]
    try:
        # Use --prefix to install into the user's home directory instead of /usr/lib
        # which requires root. The binaries go into ~/.local/bin (or npm's default prefix).
        import os
        npm_prefix = os.path.expanduser("~/.local")
        proc = await asyncio.create_subprocess_exec(
            "npm", "install", "-g", f"--prefix={npm_prefix}", *packages,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            err = (stderr or stdout or b"").decode(errors="replace").strip()
            logger.error("npm install failed for %s: %s", integration_id, err)
            raise HTTPException(status_code=500, detail=f"npm install failed: {err[:500]}")

        logger.info("Installed npm dependencies for integration %s: %s", integration_id, packages)
        return {
            "integration_id": integration_id,
            "installed": True,
            "message": "npm packages installed. Restart the server if needed.",
        }

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="npm install timed out after 120s")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to install npm deps for %s", integration_id)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Integration API key endpoints
# ---------------------------------------------------------------------------


def _get_api_permissions(integration_id: str) -> str | list[str] | None:
    """Load the api_permissions from an integration's setup.py."""
    from integrations import _iter_integration_candidates, _import_module

    for candidate, iid, is_external, source in _iter_integration_candidates():
        if iid != integration_id:
            continue
        setup_file = candidate / "setup.py"
        if not setup_file.exists():
            return None
        module = _import_module(iid, "setup", setup_file, is_external, source)
        setup = getattr(module, "SETUP", {})
        return setup.get("api_permissions")
    return None


@router.get("/integrations/{integration_id}/api-key")
async def get_integration_api_key(
    integration_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get API key metadata for an integration."""
    from app.services.api_keys import get_integration_api_key as _get_key

    api_key = await _get_key(db, integration_id)
    if not api_key:
        return {"provisioned": False}
    return {
        "provisioned": True,
        "key_prefix": api_key.key_prefix,
        "scopes": api_key.scopes,
        "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
        "last_used_at": api_key.last_used_at.isoformat() if api_key.last_used_at else None,
    }


@router.post("/integrations/{integration_id}/api-key")
async def provision_or_regenerate_integration_api_key(
    integration_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Provision a new API key or regenerate an existing one for an integration."""
    from app.services.api_keys import (
        provision_integration_api_key,
        resolve_scopes,
        revoke_integration_api_key,
    )

    api_permissions = _get_api_permissions(integration_id)
    if not api_permissions:
        raise HTTPException(
            status_code=400,
            detail=f"Integration {integration_id!r} does not declare api_permissions",
        )

    scopes = resolve_scopes(api_permissions)

    # If regenerating, revoke the old key first
    await revoke_integration_api_key(db, integration_id)

    key, full_value = await provision_integration_api_key(db, integration_id, scopes)
    return {
        "key_prefix": key.key_prefix,
        "key_value": full_value,
        "scopes": key.scopes,
        "created_at": key.created_at.isoformat() if key.created_at else None,
    }


# ---------------------------------------------------------------------------
# Integration task endpoints (generic — works for ANY integration)
# ---------------------------------------------------------------------------


@router.get("/integrations/{integration_id}/tasks")
async def list_integration_tasks(
    integration_id: str,
    status: str | None = Query(None, description="Filter by task status"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List recent tasks for an integration, filtered by dispatch_type."""
    q = select(Task).where(Task.dispatch_type == integration_id).order_by(Task.created_at.desc()).limit(limit)
    if status:
        q = q.where(Task.status == status)
    rows = (await db.execute(q)).scalars().all()

    # Also fetch aggregate counts
    count_q = (
        select(Task.status, func.count())
        .where(Task.dispatch_type == integration_id)
        .group_by(Task.status)
    )
    count_rows = (await db.execute(count_q)).all()
    stats = {row[0]: row[1] for row in count_rows}

    return {
        "tasks": [
            {
                "id": str(t.id),
                "status": t.status,
                "prompt": (t.prompt or "")[:120],
                "title": t.title,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "error": (t.error or "")[:200] if t.error else None,
                "bot_id": t.bot_id,
                "task_type": t.task_type,
            }
            for t in rows
        ],
        "stats": stats,
    }


@router.post("/integrations/{integration_id}/cancel-pending-tasks")
async def cancel_integration_pending_tasks(
    integration_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Cancel all pending tasks for an integration. Use after spam incidents."""
    result = await db.execute(
        update(Task)
        .where(Task.status == "pending", Task.dispatch_type == integration_id)
        .values(status="cancelled")
    )
    count = result.rowcount
    await db.commit()

    logger.warning("cancel-pending-tasks for %s: cancelled %d tasks", integration_id, count)
    return {"cancelled": count}


# ---------------------------------------------------------------------------
# Hot-reload endpoint
# ---------------------------------------------------------------------------


@router.post("/integrations/reload")
async def reload_integrations():
    """Discover and load new integrations without restarting the server.

    Scans INTEGRATION_DIRS for new integration directories, registers routers,
    loads tools, re-indexes, and syncs skills/carapaces/workflows.

    Note: Only loads NEW integrations. Changed code in existing integrations
    requires a server restart.
    """
    from app.tools.local.admin_integrations import _reload_integrations

    try:
        from app.main import app as application
        result = await _reload_integrations(app=application)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to reload integrations")
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/integrations/{integration_id}/api-key")
async def revoke_integration_api_key_endpoint(
    integration_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Revoke an integration's API key."""
    from app.services.api_keys import revoke_integration_api_key

    revoked = await revoke_integration_api_key(db, integration_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="No API key found for this integration")
    return {"revoked": True}
