"""Admin API for secret values vault — /api/v1/admin/secret-values"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db

router = APIRouter(prefix="/secret-values", tags=["Secret Values"])


class SecretValueCreate(BaseModel):
    name: str
    value: str
    description: str = ""


class SecretValueUpdate(BaseModel):
    name: str | None = None
    value: str | None = None
    description: str | None = None


@router.get("/")
async def list_secret_values(db: AsyncSession = Depends(get_db)):
    from app.services.secret_values import list_secrets
    return await list_secrets(db)


@router.post("/", status_code=201)
async def create_secret_value(body: SecretValueCreate, db: AsyncSession = Depends(get_db)):
    from app.services.secret_values import create_secret
    try:
        return await create_secret(db, name=body.name, value=body.value, description=body.description)
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise HTTPException(status_code=409, detail=f"Secret with name '{body.name}' already exists")
        raise


@router.get("/{secret_id}")
async def get_secret_value(secret_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    from app.services.secret_values import list_secrets
    secrets = await list_secrets(db)
    for s in secrets:
        if s["id"] == str(secret_id):
            return s
    raise HTTPException(status_code=404, detail="Secret not found")


@router.put("/{secret_id}")
async def update_secret_value(secret_id: uuid.UUID, body: SecretValueUpdate, db: AsyncSession = Depends(get_db)):
    from app.services.secret_values import update_secret
    result = await update_secret(db, secret_id, name=body.name, value=body.value, description=body.description)
    if result is None:
        raise HTTPException(status_code=404, detail="Secret not found")
    return result


@router.delete("/{secret_id}")
async def delete_secret_value(secret_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    from app.services.secret_values import delete_secret
    deleted = await delete_secret(db, secret_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Secret not found")
    return {"ok": True}
