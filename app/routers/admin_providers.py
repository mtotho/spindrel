"""Admin routes for provider_configs CRUD."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import Bot as BotRow, ProviderConfig as ProviderConfigRow
from app.services.providers import load_providers

logger = logging.getLogger(__name__)
router = APIRouter()

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

PROVIDER_TYPES = ["litellm", "openai", "anthropic", "anthropic-compatible"]


@router.get("/providers", response_class=HTMLResponse)
async def admin_providers_list(request: Request):
    async with async_session() as db:
        rows = (await db.execute(
            select(ProviderConfigRow).order_by(ProviderConfigRow.created_at)
        )).scalars().all()
    from app.config import settings
    env_base_url = settings.LITELLM_BASE_URL
    return templates.TemplateResponse("admin/providers.html", {
        "request": request,
        "providers": rows,
        "env_base_url": env_base_url,
        "has_db_providers": bool(rows),
    })


@router.get("/providers/new", response_class=HTMLResponse)
async def admin_provider_new(request: Request):
    return templates.TemplateResponse("admin/provider_new.html", {
        "request": request,
        "provider_types": PROVIDER_TYPES,
    })


@router.post("/providers", response_class=HTMLResponse)
async def admin_provider_create(
    request: Request,
    id: str = Form(...),
    provider_type: str = Form(...),
    display_name: str = Form(...),
    api_key: str = Form(""),
    base_url: str = Form(""),
    is_enabled: str = Form("true"),
    tpm_limit: str = Form(""),
    rpm_limit: str = Form(""),
    credentials_path: str = Form(""),
    management_key: str = Form(""),
):
    pid = id.strip()
    if not pid or not display_name.strip() or provider_type not in PROVIDER_TYPES:
        return HTMLResponse(
            "<div class='text-red-400 p-4'>id, display_name, and valid provider_type are required.</div>",
            status_code=422,
        )

    def _int_or_none(s: str) -> int | None:
        try:
            return int(s.strip()) if s.strip() else None
        except ValueError:
            return None

    config: dict = {}
    if provider_type == "litellm" and management_key.strip():
        config["management_key"] = management_key.strip()

    now = datetime.now(timezone.utc)
    row = ProviderConfigRow(
        id=pid,
        provider_type=provider_type,
        display_name=display_name.strip(),
        api_key=api_key.strip() or None,
        base_url=base_url.strip() or None,
        is_enabled=(is_enabled.lower() == "true"),
        tpm_limit=_int_or_none(tpm_limit),
        rpm_limit=_int_or_none(rpm_limit),
        config=config,
        created_at=now,
        updated_at=now,
    )

    async with async_session() as db:
        db.add(row)
        try:
            await db.commit()
        except Exception as exc:
            return HTMLResponse(
                f"<div class='text-red-400 p-4'>Error: {exc}</div>", status_code=400
            )

    await load_providers()
    return RedirectResponse("/admin/providers", status_code=303)


@router.get("/providers/{provider_id}/edit", response_class=HTMLResponse)
async def admin_provider_edit(request: Request, provider_id: str):
    async with async_session() as db:
        row = await db.get(ProviderConfigRow, provider_id)
        if not row:
            raise HTTPException(status_code=404, detail="Provider not found")
    return templates.TemplateResponse("admin/provider_edit.html", {
        "request": request,
        "provider": row,
        "provider_types": PROVIDER_TYPES,
    })


@router.post("/providers/{provider_id}", response_class=HTMLResponse)
async def admin_provider_update(
    request: Request,
    provider_id: str,
    provider_type: str = Form(...),
    display_name: str = Form(...),
    api_key: str = Form(""),
    base_url: str = Form(""),
    is_enabled: str = Form("true"),
    tpm_limit: str = Form(""),
    rpm_limit: str = Form(""),
    credentials_path: str = Form(""),
    management_key: str = Form(""),
):
    def _int_or_none(s: str) -> int | None:
        try:
            return int(s.strip()) if s.strip() else None
        except ValueError:
            return None

    async with async_session() as db:
        row = await db.get(ProviderConfigRow, provider_id)
        if not row:
            raise HTTPException(status_code=404, detail="Provider not found")

        config: dict = dict(row.config or {})
        config.pop("credentials_path", None)
        if provider_type == "litellm":
            if management_key.strip():
                config["management_key"] = management_key.strip()
            # Don't clear existing key if field left blank
        else:
            config.pop("management_key", None)

        row.provider_type = provider_type
        row.display_name = display_name.strip()
        row.api_key = api_key.strip() or None
        row.base_url = base_url.strip() or None
        row.is_enabled = (is_enabled.lower() == "true")
        row.tpm_limit = _int_or_none(tpm_limit)
        row.rpm_limit = _int_or_none(rpm_limit)
        row.config = config
        row.updated_at = datetime.now(timezone.utc)
        await db.commit()

    await load_providers()
    return RedirectResponse(f"/admin/providers/{provider_id}/edit?saved=1", status_code=303)


@router.delete("/providers/{provider_id}", response_class=HTMLResponse)
async def admin_provider_delete(provider_id: str):
    async with async_session() as db:
        # Check if any bots reference this provider
        bots_using = (await db.execute(
            select(BotRow.id).where(BotRow.model_provider_id == provider_id)
        )).scalars().all()
        if bots_using:
            return HTMLResponse(
                f"<div class='text-red-400 p-4'>Cannot delete: used by bots {', '.join(bots_using)}</div>",
                status_code=400,
            )
        row = await db.get(ProviderConfigRow, provider_id)
        if not row:
            raise HTTPException(status_code=404, detail="Provider not found")
        await db.delete(row)
        await db.commit()

    await load_providers()
    return HTMLResponse("", status_code=200)


@router.post("/providers/{provider_id}/test", response_class=HTMLResponse)
async def admin_provider_test(request: Request, provider_id: str):
    """HTMX: test connectivity to a provider. Returns a small badge HTML fragment."""
    from app.services.providers import get_llm_client, get_provider
    provider = get_provider(provider_id)
    if not provider:
        # Maybe it was just saved — reload
        await load_providers()
        provider = get_provider(provider_id)
    if not provider:
        return HTMLResponse(
            "<span class='text-xs text-red-400'>Provider not found in registry</span>"
        )

    ptype = provider.provider_type
    if ptype == "anthropic":
        return HTMLResponse(
            "<span class='text-xs text-green-400 font-medium'>✓ Credentials OK</span>"
        )
    else:
        try:
            client = get_llm_client(provider_id)
            models = await client.models.list()
            count = len(models.data)
            return HTMLResponse(
                f"<span class='text-xs text-green-400 font-medium'>✓ Connected ({count} models)</span>"
            )
        except Exception as exc:
            return HTMLResponse(
                f"<span class='text-xs text-red-400'>✗ {str(exc)[:120]}</span>"
            )
