"""Integration setup status, settings management, process control, and dependency management."""
from __future__ import annotations

import asyncio
import logging
import sys

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.services.integration_processes import process_manager

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_setup_vars(integration_id: str) -> list[dict]:
    """Load the SETUP env_vars list for an integration from its setup.py."""
    from integrations import _iter_integration_candidates, _import_module

    for candidate, iid, is_external, source in _iter_integration_candidates():
        if iid != integration_id:
            continue
        setup_file = candidate / "setup.py"
        if not setup_file.exists():
            return []
        module = _import_module(iid, "setup", setup_file, is_external, source)
        setup = getattr(module, "SETUP", {})
        return setup.get("env_vars", [])
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


@router.get("/integrations/sidebar-sections")
async def list_sidebar_sections():
    """Return sidebar sections declared by integrations via their SETUP manifests."""
    from integrations import discover_sidebar_sections

    return {"sections": discover_sidebar_sections()}


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
