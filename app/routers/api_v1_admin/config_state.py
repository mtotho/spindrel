"""Config state: GET /config-state, POST /config-state/restore."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/config-state")
async def get_config_state(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    from app.services.config_export import assemble_config_state

    return await assemble_config_state(db)


async def do_restore(payload: dict, db: AsyncSession) -> dict:
    """Compatibility wrapper for callers that still import router restore."""
    from app.services.config_state_restore import restore_config_state_snapshot

    return await restore_config_state_snapshot(payload, db)


@router.post("/config-state/restore")
async def restore_config_state(
    payload: dict,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    """Restore config from a backup JSON snapshot."""
    summary = await do_restore(payload, db)
    await db.commit()

    try:
        from app.agent.bots import load_bots
        from app.services.mcp_servers import load_mcp_servers
        from app.services.providers import load_providers

        await load_bots()
        await load_providers()
        await load_mcp_servers()
    except Exception as exc:
        log.warning("Post-restore reload failed: %s", exc)

    return {"status": "ok", "summary": summary}
