"""GET /admin/harnesses — list registered agent-harness runtimes + auth status.

Phase 1 surface: enumerate registered runtimes, report whether each is logged
in, surface each runtime's suggested first-run command, and report
``HARNESS_WORKSPACES_ROOT`` mount health so the admin UI can show a setup
banner with the right docker-compose snippet to paste.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends

from app.dependencies import require_scopes
from app.services.agent_harnesses import HARNESS_REGISTRY


router = APIRouter()


def _workspace_root() -> str:
    """Convention for the per-bot workspace parent dir, env-overridable."""
    return os.environ.get("HARNESS_WORKSPACES_ROOT", "/data/harness")


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
      ],
      "workspace_root": {
        "path": "/data/harness",
        "exists": true,
        "writable": true
      }
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

    root = _workspace_root()
    exists = os.path.isdir(root)
    writable = exists and os.access(root, os.W_OK)

    return {
        "runtimes": runtimes,
        "workspace_root": {
            "path": root,
            "exists": exists,
            "writable": writable,
        },
    }
