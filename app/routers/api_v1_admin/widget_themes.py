"""Widget theme library admin API."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.services import server_settings
from app.services.widget_themes import (
    BUILTIN_WIDGET_THEME_REF,
    create_widget_theme,
    delete_widget_theme,
    fork_widget_theme,
    list_widget_themes,
    normalize_widget_theme_ref,
    resolve_widget_theme,
    update_widget_theme,
)

router = APIRouter()


class WidgetThemeOut(BaseModel):
    ref: str
    name: str
    slug: str
    is_builtin: bool
    forked_from_ref: Optional[str] = None
    light_tokens: dict[str, str]
    dark_tokens: dict[str, str]
    custom_css: str = ""
    created_by: Optional[str] = None
    created_at: Any = None
    updated_at: Any = None


class WidgetThemeCreateIn(BaseModel):
    name: str = Field(min_length=1)
    slug: Optional[str] = None
    light_tokens: Optional[dict[str, str]] = None
    dark_tokens: Optional[dict[str, str]] = None
    custom_css: Optional[str] = None


class WidgetThemeUpdateIn(BaseModel):
    name: Optional[str] = None
    light_tokens: Optional[dict[str, str]] = None
    dark_tokens: Optional[dict[str, str]] = None
    custom_css: Optional[str] = None


class WidgetThemeForkIn(BaseModel):
    name: str = Field(min_length=1)
    slug: Optional[str] = None


class WidgetThemeApplyGlobalIn(BaseModel):
    ref: str = Field(min_length=1)


def _created_by(auth: Any) -> str | None:
    user_id = getattr(auth, "id", None)
    if user_id is not None:
        return str(user_id)
    return None


def _raise_theme_error(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc))
    raise HTTPException(status_code=400, detail=str(exc))


@router.get("/widget-themes", response_model=list[WidgetThemeOut])
async def admin_list_widget_themes(
    db: AsyncSession = Depends(get_db),
    _auth: Any = Depends(require_scopes("channels:read")),
):
    return [WidgetThemeOut.model_validate(row) for row in await list_widget_themes(db)]


@router.get("/widget-themes/{theme_ref:path}", response_model=WidgetThemeOut)
async def admin_get_widget_theme(
    theme_ref: str,
    db: AsyncSession = Depends(get_db),
    _auth: Any = Depends(require_scopes("channels:read")),
):
    try:
        return WidgetThemeOut.model_validate(await resolve_widget_theme(db, theme_ref))
    except Exception as exc:
        _raise_theme_error(exc)


@router.post("/widget-themes", response_model=WidgetThemeOut, status_code=201)
async def admin_create_widget_theme(
    body: WidgetThemeCreateIn,
    db: AsyncSession = Depends(get_db),
    auth: Any = Depends(require_scopes("channels.config:write")),
):
    try:
        row = await create_widget_theme(
            db,
            name=body.name,
            slug=body.slug,
            light_tokens=body.light_tokens,
            dark_tokens=body.dark_tokens,
            custom_css=body.custom_css,
            created_by=_created_by(auth),
        )
        return WidgetThemeOut.model_validate(row)
    except Exception as exc:
        _raise_theme_error(exc)


@router.put("/widget-themes/{theme_ref:path}", response_model=WidgetThemeOut)
async def admin_update_widget_theme(
    theme_ref: str,
    body: WidgetThemeUpdateIn,
    db: AsyncSession = Depends(get_db),
    _auth: Any = Depends(require_scopes("channels.config:write")),
):
    try:
        row = await update_widget_theme(
            db,
            theme_ref,
            name=body.name,
            light_tokens=body.light_tokens,
            dark_tokens=body.dark_tokens,
            custom_css=body.custom_css,
        )
        return WidgetThemeOut.model_validate(row)
    except Exception as exc:
        _raise_theme_error(exc)


@router.delete("/widget-themes/{theme_ref:path}", status_code=204)
async def admin_delete_widget_theme(
    theme_ref: str,
    db: AsyncSession = Depends(get_db),
    _auth: Any = Depends(require_scopes("channels.config:write")),
):
    try:
        await delete_widget_theme(db, theme_ref)
    except Exception as exc:
        _raise_theme_error(exc)


@router.post("/widget-themes/{theme_ref:path}/fork", response_model=WidgetThemeOut, status_code=201)
async def admin_fork_widget_theme(
    theme_ref: str,
    body: WidgetThemeForkIn,
    db: AsyncSession = Depends(get_db),
    auth: Any = Depends(require_scopes("channels.config:write")),
):
    try:
        row = await fork_widget_theme(
            db,
            source_ref=theme_ref,
            name=body.name,
            slug=body.slug,
            created_by=_created_by(auth),
        )
        return WidgetThemeOut.model_validate(row)
    except Exception as exc:
        _raise_theme_error(exc)


@router.get("/widget-theme-default")
async def admin_get_widget_theme_default(
    _auth: Any = Depends(require_scopes("channels:read")),
):
    return {
        "ref": normalize_widget_theme_ref(server_settings.settings.WIDGET_THEME_DEFAULT_REF),
        "builtin_ref": BUILTIN_WIDGET_THEME_REF,
    }


@router.put("/widget-theme-default")
async def admin_set_widget_theme_default(
    body: WidgetThemeApplyGlobalIn,
    db: AsyncSession = Depends(get_db),
    _auth: Any = Depends(require_scopes("channels.config:write")),
    ):
    normalized = normalize_widget_theme_ref(body.ref)
    try:
        await resolve_widget_theme(db, normalized)
    except Exception as exc:
        _raise_theme_error(exc)
    await server_settings.update_settings({"WIDGET_THEME_DEFAULT_REF": normalized}, db)
    return {"ref": normalized, "builtin_ref": BUILTIN_WIDGET_THEME_REF}
