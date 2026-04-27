"""Integration setup status, settings management, process control, and dependency management."""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Task
from app.dependencies import get_db, require_scopes
from app.services.integration_processes import process_manager

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_setup_vars(integration_id: str) -> list[dict]:
    """Load the SETUP env_vars list for an integration.

    Checks the manifest cache first (supports integration.yaml),
    then falls back to setup.py.  Auto-injects a ``SIDEBAR_ENABLED``
    setting for integrations that declare a ``sidebar_section``.
    """
    from integrations import _iter_integration_candidates, _get_setup

    for candidate, iid, is_external, source in _iter_integration_candidates():
        if iid != integration_id:
            continue
        setup = _get_setup(candidate, iid, is_external, source)
        if not setup:
            return []
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
async def list_integrations(_auth=Depends(require_scopes("integrations:read"))):
    from integrations import discover_setup_status

    base_url = ""
    try:
        from app.config import settings
        base_url = getattr(settings, "BASE_URL", "") or ""
    except Exception:
        pass

    return {"integrations": discover_setup_status(base_url)}


@router.get("/integrations/icons")
async def list_integration_icons(_auth=Depends(require_scopes("integrations:read"))):
    """Return a lightweight mapping of integration_id -> lucide icon name."""
    from integrations import discover_setup_status

    statuses = discover_setup_status()
    icons = {s["id"]: s.get("icon", "Plug") for s in statuses}
    return {"icons": icons}


@router.get("/integrations/sidebar-sections")
async def list_sidebar_sections(_auth=Depends(require_scopes("integrations:read"))):
    """Return sidebar sections declared by integrations via their SETUP manifests.

    Filters out sections whose integration has ``SIDEBAR_ENABLED`` set to ``"false"``.
    """
    from integrations import discover_sidebar_sections
    from app.services.integration_settings import get_value, is_active

    sections = discover_sidebar_sections()
    visible = []
    for section in sections:
        iid = section["integration_id"]
        # Only show sidebar entries for integrations that are both adopted
        # AND configured — an enabled-but-unconfigured integration's pages
        # can't actually run, so linking to them would be misleading.
        if not is_active(iid):
            continue
        enabled = get_value(iid, "SIDEBAR_ENABLED", "true")
        if enabled.lower() != "false":
            visible.append(section)
    return {"sections": visible}


# ---------------------------------------------------------------------------
# Lifecycle status
# ---------------------------------------------------------------------------


class StatusBody(BaseModel):
    status: str  # "available" | "enabled"


@router.put("/integrations/{integration_id}/status")
async def set_integration_status(integration_id: str, body: StatusBody, _auth=Depends(require_scopes("integrations:write"))):
    """Transition an integration between ``available`` and ``enabled``.

    Lifecycle is the user's explicit intent — *not* a function of config
    completeness. An enabled integration whose required settings are missing
    remains enabled; it's shown with a "Needs Setup" badge in the UI and its
    process simply won't auto-start. Readiness is derived from
    ``is_configured`` in the callers that care (auto-start, sidebar gating).
    """
    from app.services.integration_settings import get_status, set_status

    target = body.status.strip().lower()
    if target not in ("available", "enabled"):
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status!r}")

    previous = get_status(integration_id)
    if previous == target:
        return {"integration_id": integration_id, "status": target}

    # Persist the new state first so downstream reads see it.
    await set_status(integration_id, target)  # type: ignore[arg-type]

    if target == "available":
        # Tear down: stop process, unregister tools, drop embeddings.
        # IntegrationSetting rows stay so re-adding restores the old config.
        try:
            await process_manager.stop(integration_id)
        except Exception:
            logger.debug("No process to stop for %s", integration_id, exc_info=True)
        from app.tools.registry import unregister_integration_tools
        removed = unregister_integration_tools(integration_id)
        from app.agent.tools import remove_integration_embeddings
        embed_count = await remove_integration_embeddings(integration_id)
        # Drop any harness runtime this integration registered. The runtime
        # name isn't always the integration id, so we re-scan after the
        # ``HARNESS_REGISTRY`` snapshot below to remove the entries that
        # came from this integration's harness.py.
        try:
            from app.services.agent_harnesses import HARNESS_REGISTRY, unregister_runtime
            from integrations import _iter_integration_candidates

            harness_path = None
            for candidate, iid, _is_external, _source in _iter_integration_candidates():
                if iid == integration_id:
                    harness_path = candidate / "harness.py"
                    break
            if harness_path and harness_path.is_file():
                # Remove every runtime whose adapter module path matches this
                # integration's harness.py file.
                import inspect

                drop = []
                for runtime_name, runtime in list(HARNESS_REGISTRY.items()):
                    try:
                        src = inspect.getsourcefile(type(runtime))
                    except Exception:
                        src = None
                    if src and str(harness_path) == src:
                        drop.append(runtime_name)
                for runtime_name in drop:
                    unregister_runtime(runtime_name)
        except Exception:
            logger.debug("Could not unregister harness for %s", integration_id, exc_info=True)
        logger.info(
            "Integration %s → available: removed %d tool(s), %d embedding(s)",
            integration_id, len(removed), embed_count,
        )
    else:  # enabled
        # Install per-integration deps (npm/pip/system) before tool loading
        # so freshly added integrations don't need a process restart to get
        # their CLI binaries onto PATH.
        try:
            from app.services.integration_deps import ensure_one_integration_deps

            await ensure_one_integration_deps(integration_id)
        except Exception:
            logger.warning(
                "Dependency install on enable failed for %s; tools may not load",
                integration_id, exc_info=True,
            )
        # Load tools and index. Process start is deferred — auto-start loop
        # handles it once is_configured becomes true. Manual start button on
        # the UI remains available.
        from integrations import _iter_integration_candidates
        from app.tools.loader import load_integration_tools
        loaded: list[str] = []
        for candidate, iid, _is_external, _source in _iter_integration_candidates():
            if iid == integration_id:
                loaded = load_integration_tools(candidate)
                break
        from app.agent.tools import index_local_tools
        await index_local_tools()
        # Re-sync file-managed assets after the integration flips active.
        # File sync skips inactive integrations, so enablement needs a refresh
        # pass here for newly available skills, prompts, and workflows.
        from app.services import file_sync
        await file_sync.sync_all_files()
        # If the integration ships a harness adapter, register it now so the
        # new runtime appears without a server restart.
        try:
            from app.services.agent_harnesses import discover_and_load_harnesses

            discover_and_load_harnesses()
        except Exception:
            logger.debug("Harness discovery on enable failed for %s", integration_id, exc_info=True)
        logger.info("Integration %s → enabled: loaded %d tool(s)", integration_id, len(loaded))

    # MCP servers honor the new active state.
    from app.services.mcp_servers import load_mcp_servers
    await load_mcp_servers()

    return {"integration_id": integration_id, "status": target}


@router.get("/integrations/{integration_id}/settings")
async def get_integration_settings(integration_id: str, _auth=Depends(require_scopes("integrations:read"))):
    from app.services.integration_settings import get_all_for_integration

    setup_vars = _get_setup_vars(integration_id)
    settings = get_all_for_integration(integration_id, setup_vars)
    return {"settings": settings}


async def _sync_docker_compose_stack(integration_id: str) -> None:
    """If this integration declares a docker_compose stack, start/stop it based on enabled_setting."""
    from integrations import discover_docker_compose_stacks
    from app.services.docker_stacks import stack_service
    from app.services.integration_settings import get_value as _get_int_setting

    for dc_info in discover_docker_compose_stacks():
        if dc_info["integration_id"] != integration_id:
            continue
        try:
            enabled = False
            enabled_callable = dc_info.get("enabled_callable")
            if enabled_callable is not None:
                try:
                    enabled = bool(enabled_callable())
                except Exception:
                    logger.exception("enabled_callable failed for %s", integration_id)
                    enabled = False
            elif dc_info["enabled_setting"]:
                default = dc_info.get("enabled_default", "false")
                val = _get_int_setting(integration_id, dc_info["enabled_setting"], default)
                enabled = val.lower() in ("true", "1", "yes")
            await stack_service.apply_integration_stack(
                integration_id=integration_id,
                name=dc_info["description"] or integration_id,
                compose_definition=dc_info["compose_definition"],
                project_name=dc_info["project_name"],
                enabled=enabled,
                description=dc_info["description"],
                config_files=dc_info["config_files"],
            )
        except Exception:
            logger.exception("Failed to sync docker stack for %s", integration_id)
        break


class UpdateSettingsBody(BaseModel):
    settings: dict[str, str]


@router.put("/integrations/{integration_id}/settings")
async def update_integration_settings(
    integration_id: str,
    body: UpdateSettingsBody,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("integrations:write")),
):
    from app.services.integration_settings import update_settings

    setup_vars = _get_setup_vars(integration_id)
    valid_keys = {v["key"] for v in setup_vars}
    bad_keys = set(body.settings.keys()) - valid_keys
    if bad_keys:
        raise HTTPException(status_code=422, detail=f"Unknown setting keys: {', '.join(sorted(bad_keys))}")

    applied = await update_settings(integration_id, body.settings, setup_vars, db)

    # If a docker_compose.enabled_setting was toggled, start/stop the stack immediately
    await _sync_docker_compose_stack(integration_id)

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

    # Refresh MCP servers — configuration change may activate/deactivate
    # servers or rotate api keys resolved from integration settings. Clear
    # the tools/list cache so the next fetch picks up the new auth.
    from app.services.mcp_servers import load_mcp_servers
    from app.tools.mcp import _cache as _mcp_tools_cache
    await load_mcp_servers()
    _mcp_tools_cache.clear()

    return {"applied": applied}


@router.delete("/integrations/{integration_id}/settings/{key}")
async def delete_integration_setting(
    integration_id: str,
    key: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("integrations:write")),
):
    from app.services.integration_settings import delete_setting

    await delete_setting(integration_id, key, db)
    return {"deleted": key}


# ---------------------------------------------------------------------------
# Process control endpoints
# ---------------------------------------------------------------------------


@router.get("/integrations/{integration_id}/process")
async def get_process_status(integration_id: str, _auth=Depends(require_scopes("integrations:read"))):
    return process_manager.status(integration_id)


@router.post("/integrations/{integration_id}/process/start")
async def start_process(integration_id: str, _auth=Depends(require_scopes("integrations:write"))):
    from app.services.integration_settings import get_status, is_configured
    if get_status(integration_id) != "enabled":
        raise HTTPException(status_code=400, detail="Integration is not enabled")
    if not is_configured(integration_id):
        raise HTTPException(status_code=400, detail="Integration is missing required settings")
    ok = await process_manager.start(integration_id)
    if not ok:
        status = process_manager.status(integration_id)
        if status["status"] == "running":
            raise HTTPException(status_code=409, detail="Process is already running")
        # Try to give a more specific error
        state = process_manager._states.get(integration_id)
        if state and state.required_env:
            from app.services.integration_settings import get_value as _get_int_val
            missing = [k for k in state.required_env
                       if not os.environ.get(k) and not _get_int_val(integration_id, k)]
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing required settings: {', '.join(missing)}",
                )
        raise HTTPException(status_code=400, detail="Failed to start process (check server logs)")
    return process_manager.status(integration_id)


@router.post("/integrations/{integration_id}/process/stop")
async def stop_process(integration_id: str, _auth=Depends(require_scopes("integrations:write"))):
    ok = await process_manager.stop(integration_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Process is not running")
    return process_manager.status(integration_id)


@router.post("/integrations/{integration_id}/process/restart")
async def restart_process(integration_id: str, _auth=Depends(require_scopes("integrations:write"))):
    ok = await process_manager.restart(integration_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to restart process")
    return process_manager.status(integration_id)


class AutoStartBody(BaseModel):
    enabled: bool


@router.put("/integrations/{integration_id}/process/auto-start")
async def set_auto_start(integration_id: str, body: AutoStartBody, _auth=Depends(require_scopes("integrations:write"))):
    await process_manager.set_auto_start(integration_id, body.enabled)
    return {"integration_id": integration_id, "auto_start": body.enabled}


@router.get("/integrations/{integration_id}/process/auto-start")
async def get_auto_start(integration_id: str, _auth=Depends(require_scopes("integrations:read"))):
    enabled = await process_manager.get_auto_start(integration_id)
    return {"integration_id": integration_id, "auto_start": enabled}


# ---------------------------------------------------------------------------
# Process logs (ring buffer)
# ---------------------------------------------------------------------------


@router.get("/integrations/{integration_id}/process/logs")
async def get_process_logs(
    integration_id: str,
    after: int = Query(0, ge=0, description="Only return lines with index > after"),
    _auth=Depends(require_scopes("integrations:read")),
):
    """Return buffered stdout lines from the integration's process."""
    return process_manager.get_recent_logs(integration_id, after=after)


# ---------------------------------------------------------------------------
# Device / connection status
# ---------------------------------------------------------------------------


@router.get("/integrations/{integration_id}/device-status")
async def get_device_status(
    integration_id: str,
    _auth=Depends(require_scopes("integrations:read")),
):
    """Return current device connection status reported by integration process."""
    from app.services.integration_device_status import device_status_store
    result = device_status_store.get(integration_id)
    if result is None:
        return {"devices": [], "updated_at": None, "stale": True}
    return result


@router.post("/integrations/{integration_id}/device-status")
async def report_device_status(
    integration_id: str,
    body: dict,
    _auth=Depends(require_scopes("integrations:write")),
):
    """Accept a device status report from an integration process."""
    from app.services.integration_device_status import device_status_store
    devices = body.get("devices", [])
    device_status_store.report(integration_id, devices)
    return {"ok": True, "count": len(devices)}


# ---------------------------------------------------------------------------
# Python dependency installation
# ---------------------------------------------------------------------------


@router.post("/integrations/{integration_id}/install-deps")
async def install_deps(integration_id: str, _auth=Depends(require_scopes("integrations:write"))):
    """Install Python dependencies for an integration.

    Uses the YAML-declared package names as the source of truth.  Falls back
    to requirements.txt if the manifest has no dependency declarations.
    """
    from integrations import _iter_integration_candidates, _get_setup

    # Find the integration directory and its declared packages
    packages: list[str] = []
    req_path: str | None = None
    for candidate, iid, is_external, source in _iter_integration_candidates():
        if iid == integration_id:
            setup = _get_setup(candidate, iid, is_external, source)
            if setup:
                for dep in setup.get("python_dependencies", []):
                    packages.append(dep["package"])
            rp = candidate / "requirements.txt"
            if rp.exists():
                req_path = str(rp)
            break

    if not packages and req_path is None:
        raise HTTPException(status_code=404, detail=f"No Python dependencies found for integration {integration_id!r}")

    try:
        # ``-U`` so pressing the button on already-satisfied deps actually
        # bumps them to the latest version that fits the spec (no-op on fresh
        # installs). Without it, `pip install foo>=0.1.0` would print
        # "already satisfied" against an existing 0.1.5 even when 0.1.10 is
        # out — defeats the "Reinstall (upgrade)" use case.
        if packages:
            # Install from YAML-declared package names (always complete)
            cmd = [sys.executable, "-m", "pip", "install", "-q", "-U", *packages]
        else:
            # Fallback to requirements.txt
            cmd = [sys.executable, "-m", "pip", "install", "-q", "-U", "-r", req_path]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            err = (stderr or stdout or b"").decode(errors="replace").strip()
            logger.error("pip install failed for %s: %s", integration_id, err)
            raise HTTPException(status_code=500, detail=f"pip install failed: {err[:500]}")

        logger.info("Installed dependencies for integration %s: %s", integration_id, packages or req_path)

        # Reload the integration's harness module (if any) in-process so the
        # admin doesn't have to restart the server to start using a freshly
        # installed runtime. Tools are still restart-only — they're loaded
        # via a separate scanner at startup.
        harness_loaded = False
        try:
            from pathlib import Path as _P
            from app.services.agent_harnesses import _import_harness_module
            for candidate, iid, _is_external, _source in _iter_integration_candidates():
                if iid != integration_id:
                    continue
                harness_file = _P(candidate) / "harness.py"
                if harness_file.is_file():
                    _import_harness_module(harness_file, integration_id)
                    harness_loaded = True
                break
        except Exception:
            logger.exception("post-install harness reload failed for %s", integration_id)

        return {
            "integration_id": integration_id,
            "installed": True,
            "harness_reloaded": harness_loaded,
            "message": (
                "Dependencies installed. Harness reloaded — ready to use."
                if harness_loaded
                else "Dependencies installed. Restart the server to activate new tools."
            ),
        }

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="pip install timed out after 120s")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to install deps for %s", integration_id)
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/integrations/{integration_id}/install-npm-deps")
async def install_npm_deps(integration_id: str, _auth=Depends(require_scopes("integrations:write"))):
    """Install npm dependencies declared in the integration manifest."""
    from integrations import _iter_integration_candidates, _get_setup

    # Find the integration and read its manifest
    npm_deps = None
    for candidate, iid, is_external, source in _iter_integration_candidates():
        if iid == integration_id:
            setup = _get_setup(candidate, iid, is_external, source)
            if setup:
                npm_deps = setup.get("npm_dependencies", [])
            break

    if not npm_deps:
        raise HTTPException(status_code=404, detail=f"No npm_dependencies found for integration {integration_id!r}")

    # Check if any dep declares a local install directory (package.json in that dir)
    local_install_dir = None
    for dep in npm_deps:
        if dep.get("local_install_dir"):
            import os
            d = dep["local_install_dir"]
            if not os.path.isabs(d):
                d = os.path.join(str(candidate), d)
            local_install_dir = d
            break

    packages = [dep["package"] for dep in npm_deps]
    try:
        if local_install_dir:
            # Install from the integration's own package.json
            proc = await asyncio.create_subprocess_exec(
                "npm", "install", "--no-audit", "--no-fund",
                cwd=local_install_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            # Global install into the user's home directory
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


@router.post("/integrations/{integration_id}/install-system-deps")
async def install_system_deps(integration_id: str, request: Request, _auth=Depends(require_scopes("integrations:write"))):
    """Install a system dependency (apt package) for an integration."""
    from app.services.integration_deps import install_system_package

    body = await request.json()
    apt_package = body.get("apt_package")
    if not apt_package or not isinstance(apt_package, str):
        raise HTTPException(status_code=400, detail="apt_package is required")

    # Basic validation — only allow simple package names
    import re
    if not re.match(r"^[a-z0-9][a-z0-9.+\-]+$", apt_package):
        raise HTTPException(status_code=400, detail=f"Invalid package name: {apt_package!r}")

    success = await install_system_package(apt_package)
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to install {apt_package}")

    return {
        "integration_id": integration_id,
        "apt_package": apt_package,
        "installed": True,
        "message": f"System package '{apt_package}' installed successfully.",
    }


# ---------------------------------------------------------------------------
# Integration API key endpoints
# ---------------------------------------------------------------------------


def _get_api_permissions(integration_id: str) -> str | list[str] | None:
    """Load the api_permissions from an integration's manifest or setup.py."""
    from integrations import _iter_integration_candidates, _get_setup

    for candidate, iid, is_external, source in _iter_integration_candidates():
        if iid != integration_id:
            continue
        setup = _get_setup(candidate, iid, is_external, source)
        if not setup:
            return None
        return setup.get("api_permissions")
    return None


@router.get("/integrations/{integration_id}/api-key")
async def get_integration_api_key(
    integration_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("integrations:read")),
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
    _auth=Depends(require_scopes("integrations:write")),
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
    _auth=Depends(require_scopes("integrations:read")),
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
    _auth=Depends(require_scopes("integrations:write")),
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
async def reload_integrations(_auth=Depends(require_scopes("integrations:write"))):
    """Discover and load new integrations without restarting the server.

    Scans INTEGRATION_DIRS for new integration directories, registers routers,
    loads tools, re-indexes, and syncs skills/workflows.

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


# ---------------------------------------------------------------------------
# Integration manifest / YAML endpoints
# ---------------------------------------------------------------------------


@router.get("/integrations/{integration_id}/manifest")
async def get_integration_manifest(
    integration_id: str,
    _auth=Depends(require_scopes("integrations:read")),
):
    """Return the full manifest for an integration, with MCP server status."""
    from app.services.integration_manifests import get_manifest, check_file_drift

    manifest = get_manifest(integration_id)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"No manifest for '{integration_id}'")

    # Enrich MCP servers with live status
    mcp_servers = manifest.get("mcp_servers", [])
    if mcp_servers:
        from app.tools.mcp import _servers
        enriched = []
        for srv in mcp_servers:
            server_id = srv.get("id", "")
            live = _servers.get(server_id)
            enriched.append({
                **srv,
                "connected": live is not None,
                "url_configured": bool(srv.get("url")),
            })
        manifest = {**manifest, "mcp_servers": enriched}

    # Check if source file has drifted
    drift = await check_file_drift(integration_id)
    if drift:
        manifest["_file_drift"] = drift

    return {"manifest": manifest}


@router.get("/integrations/{integration_id}/yaml")
async def get_integration_yaml(
    integration_id: str,
    _auth=Depends(require_scopes("integrations:read")),
):
    """Return the YAML content for the integration editor."""
    from app.services.integration_manifests import get_yaml_content, get_manifest
    import yaml

    content = await get_yaml_content(integration_id)
    if content is not None:
        return {"yaml": content, "source": "stored"}

    # Fall back: serialize manifest to YAML
    manifest = get_manifest(integration_id)
    if manifest:
        # Remove internal fields
        clean = {k: v for k, v in manifest.items()
                 if k not in ("is_enabled", "source", "source_path", "content_hash")}
        content = yaml.dump(clean, default_flow_style=False, sort_keys=False, allow_unicode=True)
        return {"yaml": content, "source": "generated"}

    raise HTTPException(status_code=404, detail=f"No manifest for '{integration_id}'")


class UpdateYamlBody(BaseModel):
    yaml: str


@router.put("/integrations/{integration_id}/yaml")
async def update_integration_yaml(
    integration_id: str,
    body: UpdateYamlBody,
    _auth=Depends(require_scopes("integrations:write")),
):
    """Update the integration manifest from edited YAML.

    Parses the YAML, validates it, updates the DB manifest + yaml_content.
    Does NOT write to the file on disk.
    """
    from app.services.integration_manifests import update_manifest

    try:
        updated = await update_manifest(integration_id, body.yaml)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {"manifest": updated}


@router.delete("/integrations/{integration_id}/api-key")
async def revoke_integration_api_key_endpoint(
    integration_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("integrations:write")),
):
    """Revoke an integration's API key."""
    from app.services.api_keys import revoke_integration_api_key

    revoked = await revoke_integration_api_key(db, integration_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="No API key found for this integration")
    return {"revoked": True}
