"""Admin API for secret values vault — /api/v1/admin/secret-values"""
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SecretValue
from app.dependencies import get_db

router = APIRouter(prefix="/secret-values", tags=["Secret Values"])

# Valid env var name: uppercase letters, digits, underscores; must start with letter or underscore
_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SecretValueCreate(BaseModel):
    name: str
    value: str
    description: str = ""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not _ENV_VAR_RE.match(v):
            raise ValueError("Name must be a valid env var (letters, digits, underscores; must start with letter or underscore)")
        return v


class SecretValueUpdate(BaseModel):
    name: str | None = None
    value: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None and not _ENV_VAR_RE.match(v):
            raise ValueError("Name must be a valid env var (letters, digits, underscores; must start with letter or underscore)")
        return v


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
    row = await db.get(SecretValue, secret_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Secret not found")
    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description or "",
        "has_value": bool(row.value),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.put("/{secret_id}")
async def update_secret_value(secret_id: uuid.UUID, body: SecretValueUpdate, db: AsyncSession = Depends(get_db)):
    from app.services.secret_values import update_secret
    try:
        result = await update_secret(db, secret_id, name=body.name, value=body.value, description=body.description)
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise HTTPException(status_code=409, detail=f"Secret with name '{body.name}' already exists")
        raise
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
