"""TrueNAS integration admin diagnostics endpoints."""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends

from integrations.sdk import verify_admin_auth
from integrations.truenas.tools.truenas import truenas_test_connection

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/diagnose")
async def diagnose(_auth=Depends(verify_admin_auth)) -> dict[str, Any]:
    """Run the same connection check used by the diagnostics widget."""
    raw = await truenas_test_connection()
    payload = json.loads(raw)
    ok = payload.get("status") == "ok"
    logger.info("TrueNAS diagnostics completed with status=%s", payload.get("status"))
    return {"ok": ok, **payload}
