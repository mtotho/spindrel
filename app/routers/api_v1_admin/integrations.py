"""Integration setup status, settings management, process control, and dependency management."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import DomainError
from app.db.models import Task
from app.dependencies import get_db, require_scopes
from app.services import integration_admin

logger = logging.getLogger(__name__)
router = APIRouter()


def _raise_http(exc: DomainError) -> None:
    raise HTTPException(status_code=exc.http_status, detail=exc.detail) from exc


def _get_setup_vars(integration_id: str) -> list[dict]:
    """Compatibility wrapper for older callers; use integration_admin directly."""
    return integration_admin.get_setup_vars(integration_id)


def _get_api_permissions(integration_id: str) -> str | list[str] | None:
    """Compatibility wrapper for older callers; use integration_admin directly."""
    return integration_admin.get_api_permissions(integration_id)


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


async def _load_enabled_integration(integration_id: str) -> int:
    """Compatibility wrapper for old tests; use integration_admin directly."""
    return await integration_admin._load_enabled_integration(integration_id)


@router.put("/integrations/{integration_id}/status")
async def set_integration_status(integration_id: str, body: StatusBody, _auth=Depends(require_scopes("integrations:write"))):
    """Transition an integration between ``available`` and ``enabled``.

    Lifecycle is the user's explicit intent — *not* a function of config
    completeness. An enabled integration whose required settings are missing
    remains enabled; it's shown with a "Needs Setup" badge in the UI and its
    process simply won't auto-start. Readiness is derived from
    ``is_configured`` in the callers that care (auto-start, sidebar gating).
    """
    try:
        return await integration_admin.set_integration_status(integration_id, body.status)
    except DomainError as exc:
        _raise_http(exc)


@router.get("/integrations/{integration_id}/settings")
async def get_integration_settings(integration_id: str, _auth=Depends(require_scopes("integrations:read"))):
    return {"settings": integration_admin.get_integration_settings(integration_id)}


async def _sync_docker_compose_stack(integration_id: str) -> None:
    """Compatibility wrapper; use integration_admin directly."""
    await integration_admin.sync_docker_compose_stack(integration_id)


class UpdateSettingsBody(BaseModel):
    settings: dict[str, str]


@router.put("/integrations/{integration_id}/settings")
async def update_integration_settings(
    integration_id: str,
    body: UpdateSettingsBody,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("integrations:write")),
):
    try:
        return await integration_admin.update_integration_settings(integration_id, body.settings, db)
    except DomainError as exc:
        _raise_http(exc)


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
    return integration_admin.get_process_status(integration_id)


@router.post("/integrations/{integration_id}/process/start")
async def start_process(integration_id: str, _auth=Depends(require_scopes("integrations:write"))):
    try:
        return await integration_admin.start_process(integration_id)
    except DomainError as exc:
        _raise_http(exc)


@router.post("/integrations/{integration_id}/process/stop")
async def stop_process(integration_id: str, _auth=Depends(require_scopes("integrations:write"))):
    try:
        return await integration_admin.stop_process(integration_id)
    except DomainError as exc:
        _raise_http(exc)


@router.post("/integrations/{integration_id}/process/restart")
async def restart_process(integration_id: str, _auth=Depends(require_scopes("integrations:write"))):
    try:
        return await integration_admin.restart_process(integration_id)
    except DomainError as exc:
        _raise_http(exc)


class AutoStartBody(BaseModel):
    enabled: bool


@router.put("/integrations/{integration_id}/process/auto-start")
async def set_auto_start(integration_id: str, body: AutoStartBody, _auth=Depends(require_scopes("integrations:write"))):
    return await integration_admin.set_auto_start(integration_id, body.enabled)


@router.get("/integrations/{integration_id}/process/auto-start")
async def get_auto_start(integration_id: str, _auth=Depends(require_scopes("integrations:read"))):
    return await integration_admin.get_auto_start(integration_id)


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
    return integration_admin.get_process_logs(integration_id, after=after)


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
    try:
        return await integration_admin.install_python_dependencies(integration_id)
    except DomainError as exc:
        _raise_http(exc)


@router.post("/integrations/{integration_id}/install-npm-deps")
async def install_npm_deps(integration_id: str, _auth=Depends(require_scopes("integrations:write"))):
    """Install npm dependencies declared in the integration manifest."""
    try:
        return await integration_admin.install_npm_dependencies(integration_id)
    except DomainError as exc:
        _raise_http(exc)


@router.post("/integrations/{integration_id}/install-system-deps")
async def install_system_deps(integration_id: str, request: Request, _auth=Depends(require_scopes("integrations:write"))):
    """Install a system dependency (apt package) for an integration."""
    body = await request.json()
    try:
        return await integration_admin.install_system_dependency(integration_id, body.get("apt_package"))
    except DomainError as exc:
        _raise_http(exc)


@router.get("/integrations/{integration_id}/api-key")
async def get_integration_api_key(
    integration_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("integrations:read")),
):
    """Get API key metadata for an integration."""
    return await integration_admin.get_integration_api_key(integration_id, db)


@router.post("/integrations/{integration_id}/api-key")
async def provision_or_regenerate_integration_api_key(
    integration_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("integrations:write")),
):
    """Provision a new API key or regenerate an existing one for an integration."""
    try:
        return await integration_admin.provision_or_regenerate_integration_api_key(integration_id, db)
    except DomainError as exc:
        _raise_http(exc)


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
    try:
        return await integration_admin.revoke_integration_api_key(integration_id, db)
    except DomainError as exc:
        _raise_http(exc)
