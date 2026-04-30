"""GET /api/v1/admin/health — authenticated server health check."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.services.runtime_identity import runtime_identity

router = APIRouter()


@router.get("/health")
async def health_check(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("admin")),
):
    """Lightweight server health: DB connectivity, uptime, active bots, version."""
    issues: list[str] = []

    # DB connectivity
    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:
        issues.append(f"Database unreachable: {e}")

    # Active bots
    try:
        from app.agent.bots import list_bots
        bots = list_bots()
        bot_count = len(bots)
    except Exception:
        bot_count = 0
        issues.append("Failed to load bots")

    identity = runtime_identity()

    return {
        "healthy": len(issues) == 0,
        "database": db_ok,
        "uptime_seconds": identity["process"]["uptime_seconds"],
        "bot_count": bot_count,
        "version": identity["version"],
        "runtime": identity,
        "issues": issues,
    }
