from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.services.machine_control import build_providers_status, delete_machine_target, enroll_machine_target

router = APIRouter()


class MachineEnrollRequest(BaseModel):
    label: str | None = None


@router.get("/machines")
async def list_machine_providers(_auth=Depends(require_scopes("integrations:read"))):
    return {"providers": build_providers_status()}


@router.post("/machines/providers/{provider_id}/enroll")
async def enroll_machine_provider_target(
    provider_id: str,
    request: Request,
    body: MachineEnrollRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("integrations:write")),
):
    try:
        return await enroll_machine_target(
            db,
            request,
            provider_id=provider_id,
            label=body.label if body else None,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/machines/providers/{provider_id}/targets/{target_id}")
async def delete_machine_provider_target(
    provider_id: str,
    target_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("integrations:write")),
) -> dict[str, Any]:
    try:
        removed = await delete_machine_target(db, provider_id=provider_id, target_id=target_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Machine target not found")
    return {"status": "ok", "provider_id": provider_id, "target_id": target_id}
