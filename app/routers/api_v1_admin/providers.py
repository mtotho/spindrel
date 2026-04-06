"""Provider CRUD + test: /providers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Bot as BotRow, ProviderConfig as ProviderConfigRow, ProviderModel
from app.dependencies import get_db, require_scopes
from app.services.provider_drivers import PROVIDER_TYPES, get_driver

router = APIRouter()


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
    billing_type: str = "usage"
    plan_cost: Optional[float] = None
    plan_period: Optional[str] = None
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
    management_key: Optional[str] = None
    billing_type: str = "usage"
    plan_cost: Optional[float] = None
    plan_period: Optional[str] = None


class ProviderUpdateIn(BaseModel):
    provider_type: Optional[str] = None
    display_name: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    is_enabled: Optional[bool] = None
    tpm_limit: Optional[int] = Field(None)
    rpm_limit: Optional[int] = Field(None)
    management_key: Optional[str] = None
    clear_tpm_limit: bool = False
    clear_rpm_limit: bool = False
    billing_type: Optional[str] = None
    plan_cost: Optional[float] = None
    plan_period: Optional[str] = None
    clear_plan_cost: bool = False


class ProviderModelOut(BaseModel):
    id: int
    provider_id: str
    model_id: str
    display_name: str | None = None
    max_tokens: int | None = None
    input_cost_per_1m: str | None = None
    output_cost_per_1m: str | None = None
    no_system_messages: bool = False
    supports_tools: bool = True
    created_at: datetime

    model_config = {"from_attributes": True}


class ProviderModelCreateIn(BaseModel):
    model_id: str
    display_name: str | None = None
    max_tokens: int | None = None
    input_cost_per_1m: str | None = None
    output_cost_per_1m: str | None = None
    no_system_messages: bool = False
    supports_tools: bool = True


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
        billing_type=row.billing_type,
        plan_cost=row.plan_cost,
        plan_period=row.plan_period,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/providers", response_model=ProviderListOut)
async def admin_list_providers(
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("providers:read")),
):
    from app.config import settings as _settings
    rows = (await db.execute(
        select(ProviderConfigRow).order_by(ProviderConfigRow.created_at)
    )).scalars().all()
    return ProviderListOut(
        providers=[_provider_to_out(r) for r in rows],
        env_fallback_base_url=_settings.LLM_BASE_URL or None,
        env_fallback_has_key=bool(_settings.LLM_API_KEY),
    )


# ---------------------------------------------------------------------------
# Provider Models CRUD (must be before {provider_id} catch-all)
# ---------------------------------------------------------------------------

@router.get("/providers/{provider_id}/models", response_model=list[ProviderModelOut])
async def admin_list_provider_models(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("providers:read")),
):
    provider = await db.get(ProviderConfigRow, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    rows = (await db.execute(
        select(ProviderModel)
        .where(ProviderModel.provider_id == provider_id)
        .order_by(ProviderModel.model_id)
    )).scalars().all()
    return [ProviderModelOut.model_validate(r) for r in rows]


@router.post("/providers/{provider_id}/models", response_model=ProviderModelOut, status_code=201)
async def admin_add_provider_model(
    provider_id: str,
    body: ProviderModelCreateIn,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("providers:write")),
):
    provider = await db.get(ProviderConfigRow, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    if not body.model_id.strip():
        raise HTTPException(status_code=422, detail="model_id is required")

    row = ProviderModel(
        provider_id=provider_id,
        model_id=body.model_id.strip(),
        display_name=body.display_name.strip() if body.display_name else None,
        max_tokens=body.max_tokens,
        input_cost_per_1m=body.input_cost_per_1m.strip() if body.input_cost_per_1m else None,
        output_cost_per_1m=body.output_cost_per_1m.strip() if body.output_cost_per_1m else None,
        no_system_messages=body.no_system_messages,
        supports_tools=body.supports_tools,
    )
    db.add(row)
    try:
        await db.commit()
        await db.refresh(row)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"Model already exists or DB error: {exc}")

    if body.no_system_messages or not body.supports_tools:
        from app.services.providers import load_providers
        await load_providers()

    return ProviderModelOut.model_validate(row)


@router.delete("/providers/{provider_id}/models/{model_pk}")
async def admin_delete_provider_model(
    provider_id: str,
    model_pk: int,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("providers:write")),
):
    row = await db.get(ProviderModel, model_pk)
    if not row or row.provider_id != provider_id:
        raise HTTPException(status_code=404, detail="Model not found")
    had_flag = row.no_system_messages or not row.supports_tools
    await db.delete(row)
    await db.commit()

    if had_flag:
        from app.services.providers import load_providers
        await load_providers()

    return {"ok": True}


@router.get("/providers/{provider_id}", response_model=ProviderOut)
async def admin_get_provider(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("providers:read")),
):
    row = await db.get(ProviderConfigRow, provider_id)
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")
    return _provider_to_out(row)


@router.post("/providers", response_model=ProviderOut, status_code=201)
async def admin_create_provider(
    body: ProviderCreateIn,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("providers:write")),
):
    pid = body.id.strip()
    if not pid or not body.display_name.strip():
        raise HTTPException(status_code=422, detail="id and display_name are required")
    if body.provider_type not in PROVIDER_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid provider_type. Must be one of: {PROVIDER_TYPES}")

    existing = await db.get(ProviderConfigRow, pid)
    if existing:
        raise HTTPException(status_code=409, detail=f"Provider '{pid}' already exists")

    from app.services.encryption import encrypt

    config: dict = {}
    if body.provider_type == "litellm" and body.management_key:
        config["management_key"] = encrypt(body.management_key.strip())

    api_key_value = body.api_key.strip() if body.api_key else None
    if api_key_value:
        api_key_value = encrypt(api_key_value)

    now = datetime.now(timezone.utc)
    row = ProviderConfigRow(
        id=pid,
        provider_type=body.provider_type,
        display_name=body.display_name.strip(),
        api_key=api_key_value,
        base_url=body.base_url.strip() if body.base_url else None,
        is_enabled=body.is_enabled,
        tpm_limit=body.tpm_limit,
        rpm_limit=body.rpm_limit,
        config=config,
        billing_type=body.billing_type,
        plan_cost=body.plan_cost,
        plan_period=body.plan_period,
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
    _auth: str = Depends(require_scopes("providers:write")),
):
    row = await db.get(ProviderConfigRow, provider_id)
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")

    from app.services.encryption import encrypt

    if body.provider_type is not None:
        if body.provider_type not in PROVIDER_TYPES:
            raise HTTPException(status_code=422, detail=f"Invalid provider_type")
        row.provider_type = body.provider_type
    if body.display_name is not None:
        row.display_name = body.display_name.strip()
    if body.api_key is not None:
        raw_key = body.api_key.strip() or None
        row.api_key = encrypt(raw_key) if raw_key else None
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
    if body.billing_type is not None:
        row.billing_type = body.billing_type
        # Clear plan fields when switching back to usage billing
        if body.billing_type == "usage":
            row.plan_cost = None
            row.plan_period = None
    if row.billing_type == "plan":
        if body.plan_cost is not None:
            row.plan_cost = body.plan_cost
        elif body.clear_plan_cost:
            row.plan_cost = None
        if body.plan_period is not None:
            row.plan_period = body.plan_period

    config = dict(row.config or {})
    if body.management_key is not None:
        if body.management_key.strip():
            config["management_key"] = encrypt(body.management_key.strip())
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
    _auth: str = Depends(require_scopes("providers:write")),
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


class ProviderTestInlineIn(BaseModel):
    provider_type: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None


async def _test_provider_connection(
    ptype: str, api_key: str | None, base_url: str | None,
) -> ProviderTestResult:
    """Test a provider connection given raw params (works for saved and unsaved configs)."""
    try:
        driver = get_driver(ptype)
    except ValueError:
        return ProviderTestResult(ok=False, message=f"Unknown provider type: {ptype}")

    ok, message = await driver.test_connection(api_key, base_url)
    return ProviderTestResult(ok=ok, message=message)


@router.post("/providers/test-inline", response_model=ProviderTestResult)
async def admin_test_provider_inline(
    body: ProviderTestInlineIn,
    _auth: str = Depends(require_scopes("providers:write")),
):
    """Test provider connection without saving — works for new/unsaved providers."""
    return await _test_provider_connection(
        body.provider_type, body.api_key, body.base_url,
    )


@router.post("/providers/{provider_id}/test", response_model=ProviderTestResult)
async def admin_test_provider(
    provider_id: str,
    _auth: str = Depends(require_scopes("providers:write")),
):
    from app.services.providers import get_provider, load_providers as _reload

    provider = get_provider(provider_id)
    if not provider:
        await _reload()
        provider = get_provider(provider_id)
    if not provider:
        return ProviderTestResult(ok=False, message="Provider not found in registry")

    return await _test_provider_connection(
        provider.provider_type, provider.api_key, provider.base_url,
    )


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


@router.get("/provider-types/{provider_type}/capabilities")
async def admin_provider_type_capabilities(
    provider_type: str,
    _auth: str = Depends(require_scopes("providers:read")),
):
    """Return capabilities for a provider type (works for unsaved/new providers)."""
    from dataclasses import asdict

    try:
        driver = get_driver(provider_type)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown provider type: {provider_type}")
    return asdict(driver.capabilities())


@router.get("/providers/{provider_id}/capabilities")
async def admin_provider_capabilities(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("providers:read")),
):
    """Return capabilities for a saved provider."""
    from dataclasses import asdict

    row = await db.get(ProviderConfigRow, provider_id)
    if not row:
        raise HTTPException(status_code=404, detail="Provider not found")
    driver = get_driver(row.provider_type)
    return asdict(driver.capabilities())


# ---------------------------------------------------------------------------
# Model sync (generic — any provider with list_models capability)
# ---------------------------------------------------------------------------


class SyncModelsResult(BaseModel):
    created: int = 0
    updated: int = 0
    total: int = 0


@router.post("/providers/{provider_id}/sync-models", response_model=SyncModelsResult)
async def admin_sync_provider_models(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    _auth: str = Depends(require_scopes("providers:write")),
):
    """Sync models from provider API into provider_models table."""
    from app.services.providers import get_provider, load_providers as _reload

    provider = get_provider(provider_id)
    if not provider:
        await _reload()
        provider = get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found in registry")

    driver = get_driver(provider.provider_type)
    caps = driver.capabilities()
    if not caps.list_models:
        raise HTTPException(status_code=400, detail="Provider does not support model listing")

    enriched = await driver.list_models_enriched(provider)
    if not enriched:
        return SyncModelsResult(total=0)

    # Get existing DB models for this provider
    existing = (await db.execute(
        select(ProviderModel).where(ProviderModel.provider_id == provider_id)
    )).scalars().all()
    existing_map = {m.model_id: m for m in existing}

    created = 0
    updated = 0
    for m in enriched:
        mid = m["id"]
        if mid in existing_map:
            # Update display name if not manually set
            row = existing_map[mid]
            changed = False
            if m.get("display") and not row.display_name:
                row.display_name = m["display"]
                changed = True
            if changed:
                updated += 1
        else:
            row = ProviderModel(
                provider_id=provider_id,
                model_id=mid,
                display_name=m.get("display"),
            )
            db.add(row)
            created += 1

    if created or updated:
        await db.commit()

    await _reload()
    return SyncModelsResult(created=created, updated=updated, total=len(enriched))


# ---------------------------------------------------------------------------
# Capability-gated endpoints (Ollama model management, etc.)
# ---------------------------------------------------------------------------


class PullModelIn(BaseModel):
    model_name: str


@router.post("/providers/{provider_id}/pull-model")
async def admin_pull_model(
    provider_id: str,
    body: PullModelIn,
    _auth: str = Depends(require_scopes("providers:write")),
):
    """Pull/download a model from the provider. Streams progress as SSE."""
    from starlette.responses import StreamingResponse

    from app.services.providers import get_provider, load_providers as _reload

    provider = get_provider(provider_id)
    if not provider:
        await _reload()
        provider = get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found in registry")

    driver = get_driver(provider.provider_type)
    if not driver.capabilities().pull_model:
        raise HTTPException(status_code=400, detail="Provider does not support model pulling")

    import json

    async def event_stream():
        try:
            async for chunk in driver.pull_model(provider, body.model_name):
                yield f"data: {json.dumps(chunk)}\n\n"
            yield f"data: {json.dumps({'status': 'success'})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'status': 'error', 'error': str(exc)[:200]})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.delete("/providers/{provider_id}/remote-models/{model_name:path}")
async def admin_delete_remote_model(
    provider_id: str,
    model_name: str,
    _auth: str = Depends(require_scopes("providers:write")),
):
    """Delete a model from the provider (e.g. remove from Ollama)."""
    from app.services.providers import get_provider, load_providers as _reload

    provider = get_provider(provider_id)
    if not provider:
        await _reload()
        provider = get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found in registry")

    driver = get_driver(provider.provider_type)
    if not driver.capabilities().delete_model:
        raise HTTPException(status_code=400, detail="Provider does not support model deletion")

    try:
        await driver.delete_model(provider, model_name)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:200])

    return {"ok": True, "message": f"Deleted {model_name}"}


@router.get("/providers/{provider_id}/remote-models/{model_name:path}/info")
async def admin_remote_model_info(
    provider_id: str,
    model_name: str,
    _auth: str = Depends(require_scopes("providers:read")),
):
    """Get detailed info/manifest for a model from the provider."""
    from app.services.providers import get_provider, load_providers as _reload

    provider = get_provider(provider_id)
    if not provider:
        await _reload()
        provider = get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found in registry")

    driver = get_driver(provider.provider_type)
    if not driver.capabilities().model_info:
        raise HTTPException(status_code=400, detail="Provider does not support model info")

    try:
        return await driver.get_model_info(provider, model_name)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:200])


@router.get("/providers/{provider_id}/running-models")
async def admin_running_models(
    provider_id: str,
    _auth: str = Depends(require_scopes("providers:read")),
):
    """Get currently loaded/running models from the provider."""
    from app.services.providers import get_provider, load_providers as _reload

    provider = get_provider(provider_id)
    if not provider:
        await _reload()
        provider = get_provider(provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found in registry")

    driver = get_driver(provider.provider_type)
    if not driver.capabilities().running_models:
        raise HTTPException(status_code=400, detail="Provider does not support running models query")

    try:
        return await driver.get_running_models(provider)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)[:200])
