"""Integration setup status and settings management."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db

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
