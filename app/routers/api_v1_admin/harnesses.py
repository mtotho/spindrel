"""GET /admin/harnesses — list registered agent-harness runtimes + auth status.

Phase 1 surface: just enumerate registered runtimes and report whether each
is logged in. Workspace list, cost summary, and per-bot session state are
deferred to Phase 2 — see ``docs/guides/agent-harnesses.md``.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import require_scopes
from app.services.agent_harnesses import HARNESS_REGISTRY

router = APIRouter()


@router.get("/harnesses")
async def list_harnesses(
    _auth: str = Depends(require_scopes("admin")),
):
    """List registered agent-harness runtimes with their auth status.

    Response shape:
    ```
    {
      "runtimes": [
        {"name": "claude-code", "ok": true, "detail": "Logged in via /home/..."}
      ]
    }
    ```
    """
    runtimes: list[dict] = []
    for name, runtime in HARNESS_REGISTRY.items():
        try:
            status = runtime.auth_status()
            runtimes.append({
                "name": name,
                "ok": bool(status.ok),
                "detail": str(status.detail),
            })
        except Exception as exc:
            runtimes.append({
                "name": name,
                "ok": False,
                "detail": f"auth_status() raised {type(exc).__name__}: {exc}",
            })
    return {"runtimes": runtimes}
