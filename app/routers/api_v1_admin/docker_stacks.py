"""Admin API for Docker Compose stacks — list, inspect, stop, destroy."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DockerStack
from app.dependencies import get_db

router = APIRouter()


class DockerStackOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    created_by_bot: str
    channel_id: uuid.UUID | None = None
    compose_definition: str
    project_name: str
    status: str
    error_message: str | None = None
    network_name: str | None = None
    container_ids: dict = {}
    exposed_ports: dict = {}
    source: str = "bot"
    integration_id: str | None = None
    connect_networks: list = []
    last_started_at: datetime | None = None
    last_stopped_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ServiceStatusOut(BaseModel):
    name: str
    state: str
    health: str | None = None
    ports: list[dict] = []


@router.get("/docker-stacks", response_model=list[DockerStackOut])
async def list_docker_stacks(
    db: AsyncSession = Depends(get_db),
    bot_id: str | None = Query(None),
    channel_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
):
    stmt = select(DockerStack).order_by(DockerStack.created_at.desc())
    if bot_id:
        stmt = stmt.where(DockerStack.created_by_bot == bot_id)
    if channel_id:
        stmt = stmt.where(DockerStack.channel_id == channel_id)
    if status:
        stmt = stmt.where(DockerStack.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return [DockerStackOut.model_validate(r) for r in rows]


@router.get("/docker-stacks/{stack_id}", response_model=DockerStackOut)
async def get_docker_stack(
    stack_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(DockerStack, stack_id)
    if not row:
        raise HTTPException(status_code=404, detail="Stack not found")
    return DockerStackOut.model_validate(row)


@router.get("/docker-stacks/{stack_id}/status", response_model=list[ServiceStatusOut])
async def get_docker_stack_status(stack_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    row = await db.get(DockerStack, stack_id)
    if not row:
        raise HTTPException(status_code=404, detail="Stack not found")

    from app.services.docker_stacks import stack_service
    services = await stack_service.get_status(row)
    return [ServiceStatusOut(name=s.name, state=s.state, health=s.health, ports=s.ports) for s in services]


@router.get("/docker-stacks/{stack_id}/logs")
async def get_docker_stack_logs(
    stack_id: uuid.UUID,
    service: str | None = Query(None),
    tail: int = Query(100),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(DockerStack, stack_id)
    if not row:
        raise HTTPException(status_code=404, detail="Stack not found")

    from app.services.docker_stacks import stack_service
    logs = await stack_service.get_logs(row, service=service, tail=tail)
    return {"logs": logs}


@router.post("/docker-stacks/{stack_id}/start", response_model=DockerStackOut)
async def start_docker_stack(stack_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    row = await db.get(DockerStack, stack_id)
    if not row:
        raise HTTPException(status_code=404, detail="Stack not found")

    from app.services.docker_stacks import stack_service
    result = await stack_service.start(row)
    return DockerStackOut.model_validate(result)


@router.post("/docker-stacks/{stack_id}/stop", response_model=DockerStackOut)
async def stop_docker_stack(stack_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    row = await db.get(DockerStack, stack_id)
    if not row:
        raise HTTPException(status_code=404, detail="Stack not found")

    from app.services.docker_stacks import stack_service
    result = await stack_service.stop(row)
    return DockerStackOut.model_validate(result)


@router.delete("/docker-stacks/{stack_id}", status_code=204)
async def destroy_docker_stack(stack_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    row = await db.get(DockerStack, stack_id)
    if not row:
        raise HTTPException(status_code=404, detail="Stack not found")
    if row.source == "integration":
        raise HTTPException(status_code=403, detail="Integration stacks cannot be destroyed — they are managed by code")

    from app.services.docker_stacks import stack_service
    await stack_service.destroy(row)
