from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.services.machine_control import (
    build_providers_status,
    create_machine_profile,
    delete_machine_profile,
    delete_machine_target,
    enroll_machine_target,
    get_machine_target_setup,
    probe_machine_target,
    update_machine_profile,
)

router = APIRouter()


class MachineEnrollRequest(BaseModel):
    label: str | None = None
    config: dict[str, Any] | None = None


class MachineProfileRequest(BaseModel):
    label: str | None = None
    config: dict[str, Any] | None = None


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
            provider_id=provider_id,
            server_base_url=str(request.base_url),
            label=body.label if body else None,
            config=body.config if body else None,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/machines/providers/{provider_id}/targets/{target_id}/probe")
async def probe_machine_provider_target(
    provider_id: str,
    target_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("integrations:write")),
):
    try:
        return await probe_machine_target(db, provider_id=provider_id, target_id=target_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/machines/providers/{provider_id}/targets/{target_id}/setup")
async def get_machine_provider_target_setup(
    provider_id: str,
    target_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("integrations:write")),
):
    try:
        return await get_machine_target_setup(
            db,
            provider_id=provider_id,
            target_id=target_id,
            server_base_url=str(request.base_url),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/machines/providers/{provider_id}/profiles")
async def create_machine_provider_profile(
    provider_id: str,
    body: MachineProfileRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("integrations:write")),
):
    try:
        return await create_machine_profile(
            db,
            provider_id=provider_id,
            label=body.label if body else None,
            config=body.config if body else None,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/machines/providers/{provider_id}/profiles/{profile_id}")
async def update_machine_provider_profile(
    provider_id: str,
    profile_id: str,
    body: MachineProfileRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("integrations:write")),
):
    try:
        return await update_machine_profile(
            db,
            provider_id=provider_id,
            profile_id=profile_id,
            label=body.label if body else None,
            config=body.config if body else None,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/machines/providers/{provider_id}/profiles/{profile_id}")
async def delete_machine_provider_profile(
    provider_id: str,
    profile_id: str,
    db: AsyncSession = Depends(get_db),
    _auth=Depends(require_scopes("integrations:write")),
) -> dict[str, Any]:
    try:
        removed = await delete_machine_profile(db, provider_id=provider_id, profile_id=profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail="Machine profile not found")
    return {"status": "ok", "provider_id": provider_id, "profile_id": profile_id}


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
