"""Provider CRUD + test: /providers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot as BotRow, ProviderConfig as ProviderConfigRow
from app.dependencies import get_db, verify_auth

router = APIRouter()

PROVIDER_TYPES = ["litellm", "openai", "anthropic", "anthropic-subscription"]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ProviderOut(BaseModel):
    id: str
    provider_type: str
    display_name: str
    base_url: Optional[str] = None
    is_enabled: bool = True
    tpm_limit: Optional[int] = None
    rpm_limit: Optional[int] = None
    config: dict = {}
    has_api_key: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProviderCreateIn(BaseModel):
    id: str
    provider_type: str
    display_name: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    is_enabled: bool = True
    tpm_limit: Optional[int] = None
    rpm_limit: Optional[int] = None
    credentials_path: Optional[str] = None
    management_key: Optional[str] = None


class ProviderUpdateIn(BaseModel):
    provider_type: Optional[str] = None
    display_name: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    is_enabled: Optional[bool] = None
    tpm_limit: Optional[int] = Field(None)
    rpm_limit: Optional[int] = Field(None)
    credentials_path: Optional[str] = None
    management_key: Optional[str] = None
    clear_tpm_limit: bool = False
    clear_rpm_limit: bool = False


class ProviderTestResult(BaseModel):
    ok: bool
    message: str


class ProviderListOut(BaseModel):
    providers: list[ProviderOut]
    env_fallback_base_url: Optional[str] = None
    env_fallback_has_key: bool = False


def _provider_to_out(row: ProviderConfigRow) -> ProviderOut:
    return ProviderOut(
        id=row.id,
        provider_type=row.provider_type,
        display_name=row.display_name,
        base_url=row.base_url,
        is_enabled=row.is_enabled,
        tpm_limit=row.tpm_limit,
        rpm_limit=row.rpm_limit,
        config={k: v for k, v in (row.config or {}).items() if k != "management_key"},
        has_api_key=bool(row.api_key),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/providers", response_model=ProviderListOut)
async def admin_list_providers(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    from app.config import settings as _settings
    rows = (await db.execute(
        select(ProviderConfigRow).order_by(ProviderConfigRow.created_at)
    )).scalars().all()
    return ProviderListOut(
        providers=[_provider_to_out(r) for r in rows],
        env_fallback_base_url=_settings.LITELLM_BASE_URL or None,
        env_fallback_has_key=bool(_settings.LITELLM_API_KEY),
    )


@router.get("/providers/{provider_id}", response_model=ProviderOut)
async def admin_get_provider(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    row = await db.get(ProviderConfigRow, provider_id)
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")
    return _provider_to_out(row)


@router.post("/providers", response_model=ProviderOut, status_code=201)
async def admin_create_provider(
    body: ProviderCreateIn,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    pid = body.id.strip()
    if not pid or not body.display_name.strip():
        raise HTTPException(status_code=422, detail="id and display_name are required")
    if body.provider_type not in PROVIDER_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid provider_type. Must be one of: {PROVIDER_TYPES}")

    existing = await db.get(ProviderConfigRow, pid)
    if existing:
        raise HTTPException(status_code=409, detail=f"Provider '{pid}' already exists")

    config: dict = {}
    if body.provider_type == "anthropic-subscription" and body.credentials_path:
        config["credentials_path"] = body.credentials_path.strip()
    if body.provider_type == "litellm" and body.management_key:
        config["management_key"] = body.management_key.strip()

    now = datetime.now(timezone.utc)
    row = ProviderConfigRow(
        id=pid,
        provider_type=body.provider_type,
        display_name=body.display_name.strip(),
        api_key=body.api_key.strip() if body.api_key else None,
        base_url=body.base_url.strip() if body.base_url else None,
        is_enabled=body.is_enabled,
        tpm_limit=body.tpm_limit,
        rpm_limit=body.rpm_limit,
        config=config,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    try:
        await db.commit()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    from app.services.providers import load_providers
    await load_providers()
    return _provider_to_out(row)


@router.put("/providers/{provider_id}", response_model=ProviderOut)
async def admin_update_provider(
    provider_id: str,
    body: ProviderUpdateIn,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    row = await db.get(ProviderConfigRow, provider_id)
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")

    if body.provider_type is not None:
        if body.provider_type not in PROVIDER_TYPES:
            raise HTTPException(status_code=422, detail=f"Invalid provider_type")
        row.provider_type = body.provider_type
    if body.display_name is not None:
        row.display_name = body.display_name.strip()
    if body.api_key is not None:
        row.api_key = body.api_key.strip() or None
    if body.base_url is not None:
        row.base_url = body.base_url.strip() or None
    if body.is_enabled is not None:
        row.is_enabled = body.is_enabled
    if body.tpm_limit is not None:
        row.tpm_limit = body.tpm_limit
    elif body.clear_tpm_limit:
        row.tpm_limit = None
    if body.rpm_limit is not None:
        row.rpm_limit = body.rpm_limit
    elif body.clear_rpm_limit:
        row.rpm_limit = None

    config = dict(row.config or {})
    if body.credentials_path is not None:
        if body.credentials_path.strip():
            config["credentials_path"] = body.credentials_path.strip()
        else:
            config.pop("credentials_path", None)
    if body.management_key is not None:
        if body.management_key.strip():
            config["management_key"] = body.management_key.strip()
        else:
            config.pop("management_key", None)
    row.config = config

    row.updated_at = datetime.now(timezone.utc)
    await db.commit()

    from app.services.providers import load_providers
    await load_providers()
    return _provider_to_out(row)


@router.delete("/providers/{provider_id}")
async def admin_delete_provider(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(verify_auth),
):
    bots_using = (await db.execute(
        select(BotRow.id).where(BotRow.model_provider_id == provider_id)
    )).scalars().all()
    if bots_using:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete: used by bots {', '.join(bots_using)}",
        )
    row = await db.get(ProviderConfigRow, provider_id)
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")
    await db.delete(row)
    await db.commit()

    from app.services.providers import load_providers
    await load_providers()
    return {"ok": True}


@router.post("/providers/{provider_id}/test", response_model=ProviderTestResult)
async def admin_test_provider(
    provider_id: str,
    _auth: str = Depends(verify_auth),
):
    from app.services.providers import get_llm_client, get_provider, load_providers as _reload

    provider = get_provider(provider_id)
    if not provider:
        await _reload()
        provider = get_provider(provider_id)
    if not provider:
        return ProviderTestResult(ok=False, message="Provider not found in registry")

    ptype = provider.provider_type
    if ptype in ("anthropic", "anthropic-subscription"):
        try:
            if ptype == "anthropic-subscription":
                from app.services.providers import _load_anthropic_subscription_token
                creds = (provider.config or {}).get("credentials_path", "~/.claude/.credentials.json")
                _load_anthropic_subscription_token(creds)
            return ProviderTestResult(ok=True, message="Credentials OK")
        except Exception as exc:
            return ProviderTestResult(ok=False, message=str(exc)[:200])
    else:
        try:
            client = get_llm_client(provider_id)
            models = await client.models.list()
            count = len(models.data)
            return ProviderTestResult(ok=True, message=f"Connected ({count} models)")
        except Exception as exc:
            return ProviderTestResult(ok=False, message=str(exc)[:200])
