"""Integration setup status: GET /admin/integrations."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


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
