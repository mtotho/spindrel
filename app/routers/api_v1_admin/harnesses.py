"""GET /admin/harnesses — list registered agent-harness runtimes + auth status.

Phase 1 surface: enumerate registered runtimes, report whether each is logged
in, and surface each runtime's suggested first-run command. Per-bot workspaces
reuse Spindrel's existing workspace mount (``WORKSPACE_HOST_DIR``); there is
intentionally no separate harness-workspace concept.
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
        {
          "name": "claude-code",
          "ok": true,
          "detail": "Logged in via /home/...",
          "suggested_command": null
        }
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
                "suggested_command": getattr(status, "suggested_command", None),
            })
        except Exception as exc:
            runtimes.append({
                "name": name,
                "ok": False,
                "detail": f"auth_status() raised {type(exc).__name__}: {exc}",
                "suggested_command": None,
            })

    return {"runtimes": runtimes}
