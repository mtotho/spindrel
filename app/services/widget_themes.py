"""Theme library for the shared HTML widget SDK."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import WidgetTheme

BUILTIN_WIDGET_THEME_REF = "builtin/default"
CUSTOM_WIDGET_THEME_PREFIX = "custom/"

BUILTIN_LIGHT_TOKENS: dict[str, str] = {
    "surface": "#f8f9fc",
    "surfaceRaised": "#ffffff",
    "surfaceOverlay": "#f3f4f6",
    "surfaceBorder": "#e5e7eb",
    "text": "#171717",
    "textMuted": "#737373",
    "textDim": "#6b7280",
    "accent": "#3b82f6",
    "accentHover": "#2563eb",
    "accentMuted": "#dbeafe",
    "accentSubtle": "#eff6ff",
    "accentBorder": "#93c5fd",
    "danger": "#dc2626",
    "dangerMuted": "#ef4444",
    "dangerSubtle": "#fef2f2",
    "dangerBorder": "#fecaca",
    "success": "#16a34a",
    "successSubtle": "#f0fdf4",
    "successBorder": "#bbf7d0",
    "warning": "#ca8a04",
    "warningSubtle": "#fefce8",
    "warningMuted": "#b45309",
    "warningBorder": "#fde68a",
    "purple": "#7c3aed",
    "purpleMuted": "#8b5cf6",
    "purpleSubtle": "#f5f3ff",
    "purpleBorder": "#ddd6fe",
    "inputBg": "#ffffff",
    "inputBorder": "#d1d5db",
    "inputText": "#171717",
    "inputBorderFocus": "#3b82f6",
    "botMessageBg": "rgba(124,58,237,0.03)",
    "codeBg": "#f3f4f6",
    "codeBorder": "rgba(0,0,0,0.08)",
    "codeText": "#c7254e",
    "linkColor": "#2563eb",
    "contentText": "#374151",
    "overlayLight": "rgba(0,0,0,0.04)",
    "overlayBorder": "rgba(0,0,0,0.08)",
    "skeletonBg": "rgba(0,0,0,0.04)",
}

BUILTIN_DARK_TOKENS: dict[str, str] = {
    "surface": "#0f1117",
    "surfaceRaised": "#171921",
    "surfaceOverlay": "#1e2029",
    "surfaceBorder": "#2e303b",
    "text": "#e5e5e5",
    "textMuted": "#999999",
    "textDim": "#666666",
    "accent": "#3b82f6",
    "accentHover": "#2563eb",
    "accentMuted": "#1e3a5f",
    "accentSubtle": "rgba(59,130,246,0.08)",
    "accentBorder": "rgba(59,130,246,0.2)",
    "danger": "#ef4444",
    "dangerMuted": "#f87171",
    "dangerSubtle": "rgba(239,68,68,0.08)",
    "dangerBorder": "rgba(239,68,68,0.15)",
    "success": "#22c55e",
    "successSubtle": "rgba(34,197,94,0.08)",
    "successBorder": "rgba(34,197,94,0.2)",
    "warning": "#eab308",
    "warningSubtle": "rgba(234,179,8,0.08)",
    "warningMuted": "#d97706",
    "warningBorder": "rgba(234,179,8,0.2)",
    "purple": "#a855f7",
    "purpleMuted": "#c084fc",
    "purpleSubtle": "rgba(168,85,247,0.08)",
    "purpleBorder": "rgba(168,85,247,0.15)",
    "inputBg": "#111111",
    "inputBorder": "#333333",
    "inputText": "#e5e5e5",
    "inputBorderFocus": "#3b82f6",
    "botMessageBg": "rgba(168,85,247,0.04)",
    "codeBg": "#1a1a1e",
    "codeBorder": "rgba(255,255,255,0.06)",
    "codeText": "#e06c75",
    "linkColor": "#5b9bd5",
    "contentText": "#d1d5db",
    "overlayLight": "rgba(255,255,255,0.06)",
    "overlayBorder": "rgba(255,255,255,0.08)",
    "skeletonBg": "rgba(255,255,255,0.04)",
}

THEME_TOKEN_KEYS = set(BUILTIN_LIGHT_TOKENS.keys())
SLUG_RE = re.compile(r"[^a-z0-9]+")


def builtin_theme_payload() -> dict[str, Any]:
    return {
        "ref": BUILTIN_WIDGET_THEME_REF,
        "name": "Default",
        "slug": "default",
        "is_builtin": True,
        "forked_from_ref": None,
        "light_tokens": dict(BUILTIN_LIGHT_TOKENS),
        "dark_tokens": dict(BUILTIN_DARK_TOKENS),
        "custom_css": "",
        "created_by": None,
        "created_at": None,
        "updated_at": None,
    }


def widget_theme_ref_for_slug(slug: str) -> str:
    return f"{CUSTOM_WIDGET_THEME_PREFIX}{slug}"


def slugify_widget_theme_name(name: str) -> str:
    slug = SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return slug or "theme"


def normalize_widget_theme_ref(ref: str | None) -> str:
    if not ref:
        return BUILTIN_WIDGET_THEME_REF
    ref = ref.strip()
    if not ref:
        return BUILTIN_WIDGET_THEME_REF
    if ref == BUILTIN_WIDGET_THEME_REF:
        return ref
    if ref.startswith(CUSTOM_WIDGET_THEME_PREFIX):
        return ref
    return widget_theme_ref_for_slug(slugify_widget_theme_name(ref))


def validate_theme_tokens(tokens: dict[str, Any] | None, *, field_name: str) -> dict[str, str]:
    if tokens is None:
        return {}
    if not isinstance(tokens, dict):
        raise ValueError(f"{field_name} must be an object")
    out: dict[str, str] = {}
    for key, value in tokens.items():
        if key not in THEME_TOKEN_KEYS:
            raise ValueError(f"Unknown token key in {field_name}: {key}")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name}.{key} must be a non-empty string")
        out[key] = value.strip()
    return out


async def _get_theme_by_slug(db: AsyncSession, slug: str) -> WidgetTheme | None:
    return (
        await db.execute(select(WidgetTheme).where(WidgetTheme.slug == slug))
    ).scalar_one_or_none()


def _serialize_theme_row(row: WidgetTheme) -> dict[str, Any]:
    light = dict(BUILTIN_LIGHT_TOKENS)
    light.update(row.light_tokens or {})
    dark = dict(BUILTIN_DARK_TOKENS)
    dark.update(row.dark_tokens or {})
    return {
        "ref": widget_theme_ref_for_slug(row.slug),
        "name": row.name,
        "slug": row.slug,
        "is_builtin": False,
        "forked_from_ref": row.forked_from_ref,
        "light_tokens": light,
        "dark_tokens": dark,
        "custom_css": row.custom_css or "",
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def list_widget_themes(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await db.execute(select(WidgetTheme).order_by(WidgetTheme.name.asc()))
    ).scalars().all()
    return [builtin_theme_payload(), *[_serialize_theme_row(row) for row in rows]]


async def resolve_widget_theme(db: AsyncSession, ref: str | None = None) -> dict[str, Any]:
    normalized = normalize_widget_theme_ref(ref)
    if normalized == BUILTIN_WIDGET_THEME_REF:
        return builtin_theme_payload()
    if not normalized.startswith(CUSTOM_WIDGET_THEME_PREFIX):
        raise ValueError(f"Unsupported widget theme ref: {ref}")
    slug = normalized.removeprefix(CUSTOM_WIDGET_THEME_PREFIX)
    row = await _get_theme_by_slug(db, slug)
    if row is None:
        raise LookupError(f"Widget theme not found: {normalized}")
    return _serialize_theme_row(row)


async def create_widget_theme(
    db: AsyncSession,
    *,
    name: str,
    slug: str | None = None,
    light_tokens: dict[str, Any] | None = None,
    dark_tokens: dict[str, Any] | None = None,
    custom_css: str | None = None,
    created_by: str | None = None,
    forked_from_ref: str | None = None,
) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("Theme name is required")
    theme_slug = slugify_widget_theme_name(slug or name)
    if theme_slug == "default":
        raise ValueError("The default theme slug is reserved")
    if await _get_theme_by_slug(db, theme_slug):
        raise ValueError(f"Widget theme slug already exists: {theme_slug}")
    row = WidgetTheme(
        slug=theme_slug,
        name=name,
        forked_from_ref=normalize_widget_theme_ref(forked_from_ref) if forked_from_ref else None,
        light_tokens=validate_theme_tokens(light_tokens, field_name="light_tokens"),
        dark_tokens=validate_theme_tokens(dark_tokens, field_name="dark_tokens"),
        custom_css=(custom_css or "").strip() or None,
        created_by=created_by,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _serialize_theme_row(row)


async def update_widget_theme(
    db: AsyncSession,
    ref: str,
    *,
    name: str | None = None,
    light_tokens: dict[str, Any] | None = None,
    dark_tokens: dict[str, Any] | None = None,
    custom_css: str | None = None,
) -> dict[str, Any]:
    normalized = normalize_widget_theme_ref(ref)
    if normalized == BUILTIN_WIDGET_THEME_REF:
        raise ValueError("The built-in widget theme cannot be edited")
    slug = normalized.removeprefix(CUSTOM_WIDGET_THEME_PREFIX)
    row = await _get_theme_by_slug(db, slug)
    if row is None:
        raise LookupError(f"Widget theme not found: {normalized}")
    if name is not None:
        next_name = name.strip()
        if not next_name:
            raise ValueError("Theme name is required")
        row.name = next_name
    if light_tokens is not None:
        row.light_tokens = validate_theme_tokens(light_tokens, field_name="light_tokens")
    if dark_tokens is not None:
        row.dark_tokens = validate_theme_tokens(dark_tokens, field_name="dark_tokens")
    if custom_css is not None:
        row.custom_css = custom_css.strip() or None
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return _serialize_theme_row(row)


async def delete_widget_theme(db: AsyncSession, ref: str) -> None:
    normalized = normalize_widget_theme_ref(ref)
    if normalized == BUILTIN_WIDGET_THEME_REF:
        raise ValueError("The built-in widget theme cannot be deleted")
    slug = normalized.removeprefix(CUSTOM_WIDGET_THEME_PREFIX)
    row = await _get_theme_by_slug(db, slug)
    if row is None:
        raise LookupError(f"Widget theme not found: {normalized}")
    await db.delete(row)
    await db.commit()


async def fork_widget_theme(
    db: AsyncSession,
    *,
    source_ref: str,
    name: str,
    slug: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    source = await resolve_widget_theme(db, source_ref)
    return await create_widget_theme(
        db,
        name=name,
        slug=slug,
        light_tokens=source["light_tokens"],
        dark_tokens=source["dark_tokens"],
        custom_css=source["custom_css"],
        created_by=created_by,
        forked_from_ref=source["ref"],
    )


def active_widget_theme_ref(channel_config: dict[str, Any] | None) -> str:
    channel_ref = (channel_config or {}).get("widget_theme_ref")
    if channel_ref:
        return normalize_widget_theme_ref(channel_ref)
    return normalize_widget_theme_ref(settings.WIDGET_THEME_DEFAULT_REF)
