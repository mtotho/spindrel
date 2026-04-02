"""GET /health — lightweight server health check."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, verify_auth_or_user

router = APIRouter()

_start_time = time.monotonic()


@router.get("/health")
async def health_check(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth_or_user),
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

    # Uptime
    uptime_seconds = int(time.monotonic() - _start_time)

    # Active bots
    try:
        from app.agent.bots import list_bots
        bots = list_bots()
        bot_count = len(bots)
    except Exception:
        bot_count = 0
        issues.append("Failed to load bots")

    # Git version (from file or env)
    version = None
    try:
        import subprocess
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
    except Exception:
        pass

    return {
        "healthy": len(issues) == 0,
        "database": db_ok,
        "uptime_seconds": uptime_seconds,
        "bot_count": bot_count,
        "version": version,
        "issues": issues,
    }
