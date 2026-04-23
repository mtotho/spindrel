"""Widget dashboards — chat-less homes for pinned widgets.

Endpoints live under ``/api/v1/widgets``:
- ``/api/v1/widgets/dashboards`` — list/create/update/delete named dashboards
- ``/api/v1/widgets/dashboards/{slug}/rail`` — per-user + everyone rail pins
- ``/api/v1/widgets/dashboard`` — pin CRUD scoped by ``?slug=``
"""
from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import ApiKeyAuth, get_db, require_scopes
from app.services.dashboard_pins import (
    DEFAULT_DASHBOARD_KEY,
    apply_dashboard_pin_config_patch,
    apply_layout_bulk,
    create_pin,
    delete_pin,
    demote_pin_from_panel,
    get_pin,
    list_pins,
    promote_pin_to_panel,
    rename_pin,
    serialize_pin,
    update_pin_envelope,
    update_pin_scope,
)
from app.services.dashboard_rail import (
    resolved_rail_state,
    resolved_rail_state_bulk,
    set_rail_pin,
    unset_rail_pin,
)
from app.services.dashboards import (
    CHANNEL_SLUG_PREFIX,
    create_dashboard,
    delete_dashboard,
    ensure_channel_dashboard,
    get_dashboard,
    is_channel_slug,
    list_dashboards,
    redirect_target_slug,
    serialize_dashboard,
    touch_last_viewed,
    update_dashboard,
)
from app.services.widget_themes import (
    BUILTIN_WIDGET_THEME_REF,
    active_widget_theme_ref,
    list_widget_themes,
    resolve_widget_theme,
)


def _auth_identity(auth) -> tuple[uuid.UUID | None, bool]:
    """Extract ``(user_id, is_admin)`` from a ``require_scopes`` return value.

    - ``ApiKeyAuth`` has no user identity (``user_id=None``). ``is_admin`` is
      true only when the key carries the ``admin`` scope — a non-admin
      scoped key with ``channels:write`` can still pass the route guard but
      must not be allowed to pin dashboards "for everyone".
    - ``User`` → ``(user.id, user.is_admin)``.
    """
    from app.db.models import User
    if isinstance(auth, ApiKeyAuth):
        return (None, "admin" in auth.scopes)
    if isinstance(auth, User):
        return (auth.id, bool(auth.is_admin))
    return (None, False)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/widgets", tags=["widget-dashboard"])


# ---------------------------------------------------------------------------
# Dashboards (named board CRUD)
# ---------------------------------------------------------------------------
class CreateDashboardRequest(BaseModel):
    slug: str
    name: str
    icon: str | None = None
    grid_config: dict | None = None


class UpdateDashboardRequest(BaseModel):
    name: str | None = None
    icon: str | None = None
    grid_config: dict | None = None


class SetRailPinRequest(BaseModel):
    scope: Literal["everyone", "me"]
    rail_position: int | None = None


class WidgetThemeResolveOut(BaseModel):
    theme_ref: str
    explicit_channel_theme_ref: str | None = None
    global_theme_ref: str
    builtin_theme_ref: str = BUILTIN_WIDGET_THEME_REF
    theme: dict


@router.get(
    "/dashboards",
)
async def list_all_dashboards(
    scope: str = Query(
        default="user",
        description="One of 'user' | 'channel' | 'all'. "
                    "Defaults to 'user' (tab-bar friendly).",
    ),
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    if scope not in ("user", "channel", "all"):
        raise HTTPException(400, "scope must be one of 'user', 'channel', 'all'")
    rows = await list_dashboards(db, scope=scope)  # type: ignore[arg-type]
    user_id, _is_admin = _auth_identity(auth)
    rail_by_slug = await resolved_rail_state_bulk(
        db, [r.slug for r in rows], user_id,
    )
    return {
        "dashboards": [
            serialize_dashboard(r, rail=rail_by_slug.get(r.slug))
            for r in rows
        ],
    }


@router.get(
    "/dashboards/redirect-target",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_redirect_target(db: AsyncSession = Depends(get_db)):
    return {"slug": await redirect_target_slug(db)}


@router.get(
    "/dashboards/channel-pins",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def list_channel_dashboard_pins(db: AsyncSession = Depends(get_db)):
    """Pins grouped by channel — used by the "Add widget → From channel" tab.

    Returns every ``channel:<uuid>`` dashboard that has ≥1 pin, with the
    channel's display name resolved from the Channel table. Pin rows use the
    same shape as ``/dashboard`` for drop-in reuse on the frontend.
    """
    from sqlalchemy import select
    from app.db.models import (
        Channel,
        WidgetDashboard,
        WidgetDashboardPin,
    )

    # Single query: channel dashboards with their pins + channel metadata.
    # Outer-join to Channel so pins whose channel got deleted still surface
    # (client can render "deleted channel" gracefully).
    stmt = (
        select(WidgetDashboardPin, WidgetDashboard.slug, Channel.id, Channel.name)
        .join(
            WidgetDashboard,
            WidgetDashboard.slug == WidgetDashboardPin.dashboard_key,
        )
        .join(
            Channel,
            Channel.id == WidgetDashboardPin.source_channel_id,
            isouter=True,
        )
        .where(WidgetDashboard.slug.like(f"{CHANNEL_SLUG_PREFIX}%"))
        .order_by(
            Channel.name.asc().nulls_last(),
            WidgetDashboardPin.position.asc(),
        )
    )
    rows = (await db.execute(stmt)).all()

    groups: dict[str, dict] = {}
    for pin, slug, channel_id, channel_name in rows:
        key = slug
        if key not in groups:
            groups[key] = {
                "dashboard_slug": slug,
                "channel_id": str(channel_id) if channel_id else None,
                "channel_name": channel_name or "(deleted channel)",
                "pins": [],
            }
        groups[key]["pins"].append(serialize_pin(pin))

    # Skip dashboards with zero pins (shouldn't appear in the query, but
    # guard defensively) and sort by channel name for stable display.
    out = [g for g in groups.values() if g["pins"]]
    out.sort(key=lambda g: (g["channel_name"].lower(), g["dashboard_slug"]))
    return {"channels": out}


# ---------------------------------------------------------------------------
# HTML widget catalog — unified view across built-in, integration, and
# channel-workspace sources so the Library + Add-widget sheet can render a
# single grouped list with provenance badges.
# ---------------------------------------------------------------------------
@router.get(
    "/html-widget-catalog",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def html_widget_catalog(db: AsyncSession = Depends(get_db)):
    """Full HTML-widget catalog, grouped by source.

    Shape::

        {
          "builtin":      [HtmlWidgetEntry, ...],
          "integrations": [{"integration_id": str, "entries": [...]}],
          "channels":     [{"channel_id": str, "channel_name": str,
                            "entries": [HtmlWidgetEntry, ...]}]
        }

    Channel scans walk every channel's workspace (mtime-cached; cheap). The
    client uses the ``source`` field on each entry (``"builtin"`` /
    ``"integration"`` / ``"channel"``) to render the provenance pill.
    """
    from sqlalchemy import select
    from app.agent.bots import get_bot
    from app.db.models import Channel
    from app.services.html_widget_scanner import (
        scan_all_integrations,
        scan_builtin,
        scan_channel,
    )

    builtin = scan_builtin()

    integrations = [
        {"integration_id": integ_id, "entries": entries}
        for integ_id, entries in scan_all_integrations()
    ]

    # Channel workspaces — iterate every channel with a bot. Empty-result
    # channels are dropped from the response.
    rows = (
        await db.execute(
            select(Channel.id, Channel.name, Channel.bot_id)
            .order_by(Channel.name.asc())
        )
    ).all()

    channel_groups: list[dict] = []
    for channel_id, channel_name, bot_id in rows:
        if not bot_id:
            continue
        bot = get_bot(bot_id)
        if bot is None:
            continue
        entries = scan_channel(str(channel_id), bot)
        if not entries:
            continue
        channel_groups.append({
            "channel_id": str(channel_id),
            "channel_name": channel_name or "(unnamed channel)",
            "entries": entries,
        })

    return {
        "builtin": builtin,
        "integrations": integrations,
        "channels": channel_groups,
    }


@router.get(
    "/themes",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def public_widget_themes(db: AsyncSession = Depends(get_db)):
    return {"themes": await list_widget_themes(db)}


@router.get(
    "/themes/resolve",
    response_model=WidgetThemeResolveOut,
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def resolve_effective_widget_theme(
    channel_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    from app.config import settings as app_settings
    from app.db.models import Channel

    explicit_channel_theme_ref: str | None = None
    config: dict | None = None
    if channel_id is not None:
        channel = await db.get(Channel, channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")
        config = channel.config or {}
        explicit_channel_theme_ref = config.get("widget_theme_ref")

    theme_ref = active_widget_theme_ref(config)
    try:
        theme = await resolve_widget_theme(db, theme_ref)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return WidgetThemeResolveOut(
        theme_ref=theme_ref,
        explicit_channel_theme_ref=explicit_channel_theme_ref,
        global_theme_ref=active_widget_theme_ref({}),
        theme=theme,
    )


@router.get(
    "/html-widget-content/builtin",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def read_builtin_widget_content(path: str = Query(...)):
    """Serve the raw HTML of a built-in widget at ``app/tools/local/widgets/<path>``.

    Path is resolved against ``BUILTIN_WIDGET_ROOT``; any target outside
    that root (via ``..``/symlinks) is rejected with 404.
    """
    from app.services.html_widget_scanner import BUILTIN_WIDGET_ROOT
    return _serve_widget_file(str(BUILTIN_WIDGET_ROOT), path)


@router.get(
    "/html-widget-content/integrations/{integration_id}",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def read_integration_widget_content(
    integration_id: str,
    path: str = Query(...),
):
    """Serve the raw HTML of an integration widget at
    ``integrations/<integration_id>/widgets/<path>``."""
    import os as _os
    from app.services.html_widget_scanner import INTEGRATIONS_ROOT
    integration_dir = (INTEGRATIONS_ROOT / integration_id).resolve()
    # Guard against `..` or absolute integration_id escaping INTEGRATIONS_ROOT.
    try:
        integration_dir.relative_to(INTEGRATIONS_ROOT)
    except ValueError:
        raise HTTPException(404, "Integration not found")
    widgets_dir = str(integration_dir / "widgets")
    if not _os.path.isdir(widgets_dir):
        raise HTTPException(404, "Integration widgets dir not found")
    return _serve_widget_file(widgets_dir, path)


@router.get(
    "/html-widget-content/library",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def read_library_widget_content(
    ref: str = Query(..., description="Library ref: '<scope>/<name>' or 'name'"),
    bot_id: str | None = Query(
        None,
        description=(
            "Bot whose library to resolve against. Required for bot/"
            "workspace scopes; core scope resolves without a bot."
        ),
    ),
):
    """Serve the current body of a ``widget://<scope>/<name>/`` bundle.

    Pairs with envelopes that carry ``source_kind='library'`` +
    ``source_library_ref='<scope>/<name>'``. Returns ``{path, content}`` to
    match the shape of the sibling builtin / integration endpoints so the
    renderer's content fetch stays uniform.
    """
    import os as _os

    ws_root: str | None = None
    shared_root: str | None = None
    if bot_id:
        from app.agent.bots import get_bot
        from app.services.shared_workspace import shared_workspace_service
        from app.services.workspace import workspace_service
        bot = get_bot(bot_id)
        if bot is None:
            raise HTTPException(404, f"Unknown bot {bot_id!r}")
        ws_root = workspace_service.get_workspace_root(bot_id, bot)
        if bot.shared_workspace_id:
            shared_root = _os.path.realpath(
                shared_workspace_service.get_host_root(bot.shared_workspace_id)
            )

    from app.tools.local.emit_html_widget import _load_library_widget
    try:
        body, meta = _load_library_widget(
            ref, ws_root=ws_root, shared_root=shared_root,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    return {"path": f"{meta['scope']}/{meta['name']}/index.html", "content": body}


def _scanner_entry_to_library(
    entry: dict,
    *,
    preferred_auth_model: str = "viewer",
) -> dict:
    """Normalize an ``html_widget_scanner`` entry into ``WidgetLibraryEntry``
    shape so the Library endpoint can return a single union-typed list
    across scopes. The scanner carries a richer payload (``path``,
    ``integration_id``, ``is_loose``, ...); we keep those fields alongside
    the common ``name/scope/format/display_label/description/...`` ones.
    """
    from app.services.widget_contracts import (
        build_public_contract_fields_for_catalog_entry,
        normalize_config_schema,
    )

    source = entry.get("source") or "channel"
    # Map scanner source → library scope verbatim.
    scope = "integration" if source == "integration" else source
    normalized = {
        "name": entry.get("name") or entry.get("slug") or "",
        "scope": scope,
        "format": "html",
        "display_label": entry.get("display_label") or entry.get("name") or "",
        "panel_title": entry.get("panel_title"),
        "show_panel_title": entry.get("show_panel_title"),
        "description": entry.get("description") or "",
        "version": entry.get("version") or "0.0.0",
        "tags": entry.get("tags") or [],
        "icon": entry.get("icon"),
        "updated_at": int(entry.get("modified_at") or 0),
        # Scanner-specific fields the pin envelope needs to round-trip so
        # the renderer can fetch content through the right endpoint.
        "path": entry.get("path"),
        "slug": entry.get("slug"),
        "integration_id": entry.get("integration_id"),
        "is_loose": bool(entry.get("is_loose", False)),
        "has_manifest": bool(entry.get("has_manifest", False)),
        "widget_kind": entry.get("widget_kind") or "html",
        "widget_binding": entry.get("widget_binding") or "standalone",
        "theme_support": entry.get("theme_support") or "html",
        "group_kind": entry.get("group_kind"),
        "group_ref": entry.get("group_ref"),
        "actions": entry.get("actions") or [],
        "widget_ref": entry.get("widget_ref"),
        "supported_scopes": entry.get("supported_scopes") or [],
        "config_schema": normalize_config_schema(entry.get("config_schema")),
    }
    normalized.update(
        build_public_contract_fields_for_catalog_entry(
            normalized,
            preferred_auth_model=preferred_auth_model,
        )
    )
    return normalized


@router.get(
    "/library-widgets",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def list_library_widgets(
    db: AsyncSession = Depends(get_db),
    bot_id: str | None = Query(
        None,
        description=(
            "Bot whose library to enumerate. Required for the bot/workspace "
            "scopes; core always returns regardless. Omit to see core + "
            "integration + (optional) channel sections only."
        ),
    ),
    channel_id: str | None = Query(
        None,
        description=(
            "Channel whose workspace HTML widgets to include under the "
            "``channel`` section. Omit to skip channel scanning."
        ),
    ),
):
    """Unified pinnable-widget catalog across every source.

    Shape::

        {
          "core":        [WidgetLibraryEntry, ...],  # widget://core/<name>
          "integration": [WidgetLibraryEntry, ...],  # integrations/<id>/widgets
          "bot":         [WidgetLibraryEntry, ...],  # widget://bot/<name>
          "workspace":   [WidgetLibraryEntry, ...],  # widget://workspace/<name>
          "channel":     [WidgetLibraryEntry, ...],  # <channel workspace>/...
        }

    ``WidgetLibraryEntry`` base fields — ``name``, ``scope``, ``format``,
    ``display_label``, ``description``, ``version``, ``tags``, ``icon``,
    ``updated_at``. Scanner-sourced scopes (``integration`` / ``channel``)
    additionally carry ``path`` / ``integration_id`` / ``is_loose`` so the
    pin envelope can route content fetches through the matching
    ``/html-widget-content/*`` endpoint.

    **Tool-renderer `template.yaml` bundles are intentionally excluded.**
    Entries like ``get_task_result``, ``manage_bot_skill``, ``schedule_task``
    need tool arguments to render and are surfaced through the dev panel's
    Tools / Recent-calls tabs instead — they can't be pinned standalone.
    """
    import os as _os

    from sqlalchemy import select

    from app.agent.bots import get_bot
    from app.db.models import Channel
    from app.services.html_widget_scanner import (
        scan_all_integrations,
        scan_channel,
    )
    from app.services.native_app_widgets import list_native_widget_catalog_entries
    from app.services.widget_contracts import build_public_contract_fields_for_catalog_entry
    from app.services.widget_paths import scope_root
    from app.tools.local.widget_library import (
        _iter_core_widgets,
        _iter_scope_dir,
    )

    ws_root: str | None = None
    shared_root: str | None = None
    if bot_id:
        from app.services.shared_workspace import shared_workspace_service
        from app.services.workspace import workspace_service
        bot = get_bot(bot_id)
        if bot is None:
            raise HTTPException(404, f"Unknown bot {bot_id!r}")
        ws_root = workspace_service.get_workspace_root(bot_id, bot)
        if bot.shared_workspace_id:
            shared_root = _os.path.realpath(
                shared_workspace_service.get_host_root(bot.shared_workspace_id)
            )

    # Core: widget://core/<name>. Filter out template-format entries —
    # those are tool renderers that need tool args to render and belong in
    # the dev panel, not a pinnable library.
    preferred_auth_model = "source_bot" if bot_id else "viewer"

    core = [w for w in _iter_core_widgets() if w.get("format") != "template"]
    core.extend(list_native_widget_catalog_entries())
    for entry in core:
        entry.update(
            build_public_contract_fields_for_catalog_entry(
                entry,
                preferred_auth_model=preferred_auth_model,
            )
        )

    # Integration widgets — use the scanner (already filters tool renderers
    # referenced by integration.yaml's tool_widgets block). Flatten the
    # per-integration grouping into a single list; each entry carries its
    # own ``integration_id`` so the UI can group/badge.
    integration_entries: list[dict] = []
    for _integ_id, entries in scan_all_integrations():
        for e in entries:
            integration_entries.append(
                _scanner_entry_to_library(
                    e,
                    preferred_auth_model=preferred_auth_model,
                )
            )

    bot_entries = _iter_scope_dir(
        scope_root("bot", ws_root=ws_root, shared_root=shared_root),
        "bot",
    )
    workspace_entries = _iter_scope_dir(
        scope_root("workspace", ws_root=ws_root, shared_root=shared_root),
        "workspace",
    )

    # Channel workspace widgets are only enumerated when caller pins down a
    # specific channel — walking every channel's workspace from a generic
    # "show me pinnable things" endpoint is expensive and noisy.
    channel_entries: list[dict] = []
    if channel_id:
        try:
            ch_uuid = uuid.UUID(channel_id)
        except ValueError:
            raise HTTPException(400, f"Invalid channel_id {channel_id!r}")
        row = (
            await db.execute(
                select(Channel.bot_id).where(Channel.id == ch_uuid)
            )
        ).first()
        if row is not None and row[0]:
            bot_for_channel = get_bot(str(row[0]))
            if bot_for_channel is not None:
                for e in scan_channel(str(ch_uuid), bot_for_channel):
                    normalized = _scanner_entry_to_library(
                        e,
                        preferred_auth_model=preferred_auth_model,
                    )
                    normalized["scope"] = "channel"
                    normalized["channel_id"] = str(ch_uuid)
                    channel_entries.append(normalized)

    return {
        "core": core,
        "integration": integration_entries,
        "bot": bot_entries,
        "workspace": workspace_entries,
        "channel": channel_entries,
    }


@router.get(
    "/library-widgets/all-bots",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def list_library_widgets_all_bots(
    channel_id: str | None = Query(
        None,
        description=(
            "Optional channel whose workspace HTML widgets should populate the "
            "``channel`` section alongside the all-bots library view."
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """Dev-panel variant of ``/library-widgets`` that enumerates EVERY bot's
    ``.widget_library/`` into one catalog. Each ``bot`` scope entry carries
    ``bot_id`` + ``bot_name`` so the UI can group/badge them. ``workspace``
    scope is deduped by shared_workspace_id so a shared library isn't
    double-counted across bots that share it. When ``channel_id`` is
    provided, the matching channel workspace also populates the ``channel``
    section so the dev panel can show the same contextual library view as
    the Add Widget sheet.
    """
    import os as _os

    from sqlalchemy import select

    from app.agent.bots import get_bot, list_bots
    from app.db.models import Channel
    from app.services.html_widget_scanner import scan_all_integrations, scan_channel
    from app.services.native_app_widgets import list_native_widget_catalog_entries
    from app.services.shared_workspace import shared_workspace_service
    from app.services.widget_contracts import build_public_contract_fields_for_catalog_entry
    from app.services.widget_paths import scope_root
    from app.services.workspace import workspace_service
    from app.tools.local.widget_library import (
        _iter_core_widgets,
        _iter_scope_dir,
    )

    core = [w for w in _iter_core_widgets() if w.get("format") != "template"]
    core.extend(list_native_widget_catalog_entries())
    for entry in core:
        entry.update(
            build_public_contract_fields_for_catalog_entry(
                entry,
                preferred_auth_model="source_bot",
            )
        )

    integration_entries: list[dict] = []
    for _integ_id, entries in scan_all_integrations():
        for e in entries:
            integration_entries.append(
                _scanner_entry_to_library(
                    e,
                    preferred_auth_model="source_bot",
                )
            )

    bot_entries: list[dict] = []
    workspace_entries: list[dict] = []
    seen_shared_roots: set[str] = set()

    for bot in list_bots():
        try:
            ws_root = workspace_service.get_workspace_root(bot.id, bot)
        except Exception:  # noqa: BLE001 — skip bots without provisioned workspaces
            continue

        for entry in _iter_scope_dir(
            scope_root("bot", ws_root=ws_root, shared_root=None),
            "bot",
        ):
            entry["bot_id"] = bot.id
            entry["bot_name"] = getattr(bot, "name", None) or bot.id
            bot_entries.append(entry)

        if bot.shared_workspace_id:
            try:
                shared_root = _os.path.realpath(
                    shared_workspace_service.get_host_root(bot.shared_workspace_id)
                )
            except Exception:  # noqa: BLE001
                continue
            if shared_root in seen_shared_roots:
                continue
            seen_shared_roots.add(shared_root)
            for entry in _iter_scope_dir(
                scope_root("workspace", ws_root=None, shared_root=shared_root),
                "workspace",
            ):
                entry["bot_id"] = bot.id
                entry["bot_name"] = getattr(bot, "name", None) or bot.id
                workspace_entries.append(entry)

    channel_entries: list[dict] = []
    if channel_id:
        try:
            ch_uuid = uuid.UUID(channel_id)
        except ValueError:
            raise HTTPException(400, f"Invalid channel_id {channel_id!r}")
        row = (
            await db.execute(
                select(Channel.bot_id).where(Channel.id == ch_uuid)
            )
        ).first()
        if row is not None and row[0]:
            bot_for_channel = get_bot(str(row[0]))
            if bot_for_channel is not None:
                for e in scan_channel(str(ch_uuid), bot_for_channel):
                    normalized = _scanner_entry_to_library(
                        e,
                        preferred_auth_model="source_bot",
                    )
                    normalized["scope"] = "channel"
                    normalized["channel_id"] = str(ch_uuid)
                    channel_entries.append(normalized)

    return {
        "core": core,
        "integration": integration_entries,
        "bot": bot_entries,
        "workspace": workspace_entries,
        "channel": channel_entries,
    }


@router.get(
    "/widget-manifest",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_widget_manifest(
    db: AsyncSession = Depends(get_db),
    scope: str = Query(..., description="Widget scope: core / bot / workspace / integration / channel."),
    name: str | None = Query(None, description="Widget bundle name (core/bot/workspace scopes)."),
    bot_id: str | None = Query(None, description="Bot id (bot/workspace scopes)."),
    integration_id: str | None = Query(None, description="Integration id (integration scope)."),
    channel_id: str | None = Query(None, description="Channel id (channel scope)."),
    path: str | None = Query(None, description="Relative bundle path (integration/channel scopes)."),
):
    """Return the parsed ``widget.yaml`` (or equivalent) for a library entry.

    Shape: ``{manifest: dict | None, raw: str | None, source_path: str}``.
    ``manifest`` is None when the bundle has no manifest file — the UI can
    then just show "No manifest declared" instead of an error.
    """
    import os as _os

    from app.services.widget_paths import scope_root
    from app.services.workspace import workspace_service
    from app.services.shared_workspace import shared_workspace_service
    from app.agent.bots import get_bot

    def _read(abs_path: str) -> dict:
        if not _os.path.isfile(abs_path):
            return {"manifest": None, "raw": None, "source_path": abs_path}
        try:
            with open(abs_path, encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except OSError:
            return {"manifest": None, "raw": None, "source_path": abs_path}
        try:
            import yaml
            parsed = yaml.safe_load(raw) or {}
        except Exception:  # noqa: BLE001 — surface raw even on parse error
            parsed = None
        return {"manifest": parsed, "raw": raw, "source_path": abs_path}

    if scope in {"core", "bot", "workspace"}:
        if not name:
            raise HTTPException(400, "name is required for core/bot/workspace scopes.")
        ws_root: str | None = None
        shared_root: str | None = None
        if scope in {"bot", "workspace"}:
            if not bot_id:
                raise HTTPException(400, "bot_id is required for bot/workspace scopes.")
            try:
                bot = get_bot(bot_id)
            except HTTPException:
                raise
            ws_root = workspace_service.get_workspace_root(bot_id, bot)
            if bot.shared_workspace_id:
                shared_root = _os.path.realpath(
                    shared_workspace_service.get_host_root(bot.shared_workspace_id)
                )
        base = scope_root(scope, ws_root=ws_root, shared_root=shared_root)
        if not base:
            raise HTTPException(404, f"Scope {scope} unavailable.")
        bundle = _os.path.join(base, name)
        for candidate in ("widget.yaml", "suite.yaml", "template.yaml"):
            p = _os.path.join(bundle, candidate)
            if _os.path.isfile(p):
                return _read(p)
        return {"manifest": None, "raw": None, "source_path": bundle}

    if scope == "integration":
        if not integration_id or not path:
            raise HTTPException(400, "integration_id + path required for integration scope.")
        # integration bundles: integrations/<id>/widgets/<path>; manifest sits
        # alongside index.html if present.
        integ_root = _os.path.realpath(
            _os.path.join(_os.getcwd(), "integrations", integration_id, "widgets")
        )
        target_dir = _os.path.dirname(_os.path.realpath(_os.path.join(integ_root, path)))
        if not target_dir.startswith(integ_root):
            raise HTTPException(400, "Invalid path.")
        manifest_path = _os.path.join(target_dir, "widget.yaml")
        return _read(manifest_path)

    if scope == "channel":
        if not channel_id or not path:
            raise HTTPException(400, "channel_id + path required for channel scope.")
        from app.db.models import Channel
        from sqlalchemy import select
        try:
            ch_uuid = uuid.UUID(channel_id)
        except ValueError:
            raise HTTPException(400, f"Invalid channel_id {channel_id!r}")
        row = (
            await db.execute(select(Channel.bot_id).where(Channel.id == ch_uuid))
        ).first()
        if row is None or not row[0]:
            raise HTTPException(404, "Channel not found or has no bot.")
        bot = get_bot(str(row[0]))
        from app.services.channel_workspace import get_channel_workspace_root
        ch_root = get_channel_workspace_root(channel_id, bot)
        target_dir = _os.path.dirname(_os.path.realpath(_os.path.join(ch_root, path)))
        if not target_dir.startswith(_os.path.realpath(ch_root)):
            raise HTTPException(400, "Invalid path.")
        manifest_path = _os.path.join(target_dir, "widget.yaml")
        return _read(manifest_path)

    raise HTTPException(400, f"Unknown scope: {scope}")


def _serve_widget_file(root: str, rel_path: str) -> dict:
    """Shared read-and-return body with path-traversal guards.

    Returns ``{path, content}`` to match the channel-workspace read endpoint
    shape so the renderer can dispatch without per-source body-shape branching.
    """
    import os as _os
    root_real = _os.path.realpath(root)
    target = _os.path.realpath(_os.path.join(root, rel_path))
    if not (target == root_real or target.startswith(root_real + _os.sep)):
        raise HTTPException(404, "File not found")
    if not _os.path.isfile(target):
        raise HTTPException(404, "File not found")
    try:
        with open(target, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        raise HTTPException(404, "File not found")
    return {"path": rel_path, "content": content}


@router.get(
    "/dashboards/{slug}",
)
async def get_single_dashboard(
    slug: str,
    auth=Depends(require_scopes("channels:read")),
    db: AsyncSession = Depends(get_db),
):
    # Channel dashboards lazy-create on read so the channel UI can ask for
    # metadata (name, icon) without having to seed the row first.
    if is_channel_slug(slug):
        ch_id = slug[len(CHANNEL_SLUG_PREFIX):]
        try:
            import uuid as _uuid
            _uuid.UUID(ch_id)
        except ValueError:
            raise HTTPException(400, f"Invalid channel slug: {slug}")
        await ensure_channel_dashboard(db, ch_id)
    row = await get_dashboard(db, slug)
    user_id, _ = _auth_identity(auth)
    rail = await resolved_rail_state(db, row.slug, user_id)
    return serialize_dashboard(row, rail=rail)


@router.post(
    "/dashboards",
)
async def create_new_dashboard(
    body: CreateDashboardRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    row = await create_dashboard(
        db,
        slug=body.slug,
        name=body.name,
        icon=body.icon,
        grid_config=body.grid_config,
    )
    logger.info("Widget dashboard created: slug=%s name=%s", row.slug, row.name)
    user_id, _ = _auth_identity(auth)
    rail = await resolved_rail_state(db, row.slug, user_id)
    return serialize_dashboard(row, rail=rail)


@router.patch(
    "/dashboards/{slug}",
)
async def patch_dashboard(
    slug: str,
    body: UpdateDashboardRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    row = await update_dashboard(db, slug, body.model_dump(exclude_unset=True))
    user_id, _ = _auth_identity(auth)
    rail = await resolved_rail_state(db, row.slug, user_id)
    return serialize_dashboard(row, rail=rail)


@router.put(
    "/dashboards/{slug}/rail",
)
async def put_rail_pin(
    slug: str,
    body: SetRailPinRequest,
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    """Pin a dashboard to the sidebar rail.

    ``scope='everyone'`` is admin-only and shows the dashboard in every
    user's rail. ``scope='me'`` adds it to the current user's rail only.
    """
    # Lazy-create channel dashboards so the UI can pin a channel dashboard
    # before a pin ever lands on it.
    if is_channel_slug(slug):
        ch_id = slug[len(CHANNEL_SLUG_PREFIX):]
        try:
            uuid.UUID(ch_id)
        except ValueError:
            raise HTTPException(400, f"Invalid channel slug: {slug}")
        await ensure_channel_dashboard(db, ch_id)
    # Touches get_dashboard to raise 404 if the slug doesn't exist.
    await get_dashboard(db, slug)

    user_id, is_admin = _auth_identity(auth)
    await set_rail_pin(
        db, slug,
        scope=body.scope,
        user_id=user_id,
        is_admin=is_admin,
        rail_position=body.rail_position,
    )
    rail = await resolved_rail_state(db, slug, user_id)
    return {"slug": slug, "rail": rail}


@router.delete(
    "/dashboards/{slug}/rail",
)
async def delete_rail_pin(
    slug: str,
    scope: Literal["everyone", "me"] = Query(...),
    auth=Depends(require_scopes("channels:write")),
    db: AsyncSession = Depends(get_db),
):
    user_id, is_admin = _auth_identity(auth)
    await unset_rail_pin(
        db, slug,
        scope=scope,
        user_id=user_id,
        is_admin=is_admin,
    )
    rail = await resolved_rail_state(db, slug, user_id)
    return {"slug": slug, "rail": rail}


@router.delete(
    "/dashboards/{slug}",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def remove_dashboard(slug: str, db: AsyncSession = Depends(get_db)):
    await delete_dashboard(db, slug)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Recent widget-producing tool calls
# ---------------------------------------------------------------------------
# Used by the "Add widget" sheet's "Recent calls" tab — surfaces tool calls
# whose result is a renderable widget envelope (components, html-interactive,
# html, etc.) so users can pin them straight to a dashboard without having
# to first pin them to a channel's OmniPanel rail.
_WIDGET_CONTENT_TYPES = {
    "application/vnd.spindrel.components+json",
    "application/vnd.spindrel.html+interactive",
    "application/vnd.spindrel.diff+text",
    "application/vnd.spindrel.file-listing+json",
    "text/html",
}


@router.get(
    "/recent-calls",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def list_recent_widget_calls(
    channel_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List recent tool calls that can be rendered as a widget.

    A call qualifies if either:
    - the tool's stored ``result`` already IS an envelope (``_envelope``
      opt-in tools like ``emit_html_widget``), OR
    - a registered widget template for the tool produces one when applied
      to the stored ``result``.

    The rendered envelope is returned in each row so the UI can pin it
    directly without a second round-trip through the preview endpoints.
    """
    import json
    from sqlalchemy import select
    from app.db.models import Session as SessionModel, ToolCall, Channel
    from app.services.widget_templates import apply_widget_template

    # Pull more than `limit` up front since we filter out non-widget
    # envelopes after rendering — otherwise a page full of text results
    # would leave the user with an empty list.
    over_limit = limit * 4

    stmt = (
        select(ToolCall, SessionModel.channel_id, Channel.name)
        .join(SessionModel, SessionModel.id == ToolCall.session_id, isouter=True)
        .join(Channel, Channel.id == SessionModel.channel_id, isouter=True)
        .where(ToolCall.status == "done")
        .where(ToolCall.result.isnot(None))
        .order_by(ToolCall.created_at.desc())
    )
    if channel_id is not None:
        stmt = stmt.where(SessionModel.channel_id == channel_id)
    stmt = stmt.limit(over_limit)

    rows = (await db.execute(stmt)).all()

    out: list[dict] = []
    seen_identities: set[str] = set()
    for tool_call, row_channel_id, row_channel_name in rows:
        if len(out) >= limit:
            break
        raw = tool_call.result
        if not raw:
            continue

        envelope: dict | None = None

        # Path 1: template-rendered envelope (works for every tool with a
        # registered .widgets.yaml template). Cheap — dict lookup + a JSON
        # parse that succeeds fast on the 95% of tools that return JSON.
        try:
            rendered = apply_widget_template(tool_call.tool_name, raw)
        except Exception:
            rendered = None
        if rendered is not None:
            envelope = rendered.compact_dict()

        # Path 2: tool-shipped envelope via the ``_envelope`` opt-in wrapper
        # (``emit_html_widget`` and any bot-authored widget tool). Stored
        # shape is ``{"_envelope": {...content_type, body, ...}, "llm": "..."}``
        # — we unwrap and accept if the inner envelope is a widget type.
        if envelope is None:
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if not isinstance(parsed, dict):
                continue
            inner = parsed.get("_envelope")
            if isinstance(inner, dict) and inner.get("content_type") in _WIDGET_CONTENT_TYPES:
                envelope = inner
            elif parsed.get("content_type") in _WIDGET_CONTENT_TYPES:
                # Legacy shape — result itself IS the envelope.
                envelope = parsed
            else:
                continue

        # De-dupe: tool_name + first 120 chars of body is a good-enough
        # identity for "is this the same widget I already saw 3 calls up".
        body = envelope.get("body")
        body_str = body if isinstance(body, str) else json.dumps(body or "")
        identity = f"{tool_call.tool_name}::{body_str[:120]}"
        if identity in seen_identities:
            continue
        seen_identities.add(identity)
        out.append({
            "id": str(tool_call.id),
            "tool_name": tool_call.tool_name,
            "bot_id": tool_call.bot_id,
            "channel_id": str(row_channel_id) if row_channel_id else None,
            "channel_name": row_channel_name,
            "tool_args": tool_call.arguments or {},
            "envelope": envelope,
            "display_label": envelope.get("display_label"),
            "created_at": tool_call.created_at.isoformat() if tool_call.created_at else None,
        })
    return {"calls": out}


# ---------------------------------------------------------------------------
# Pins (scoped by ?slug= query param — defaults to 'default')
# ---------------------------------------------------------------------------
class CreatePinRequest(BaseModel):
    source_kind: str  # 'channel' | 'adhoc'
    tool_name: str
    envelope: dict
    source_channel_id: uuid.UUID | None = None
    source_bot_id: str | None = None
    tool_args: dict | None = None
    widget_config: dict | None = None
    display_label: str | None = None
    dashboard_key: str | None = None
    zone: str | None = None
    grid_layout: dict | None = None


class PreviewForToolRequest(BaseModel):
    tool_name: str
    tool_args: dict | None = None
    widget_config: dict | None = None
    source_bot_id: str | None = None
    source_channel_id: uuid.UUID | None = None


class WidgetPresetPreviewRequest(BaseModel):
    config: dict | None = None
    source_bot_id: str | None = None
    source_channel_id: uuid.UUID | None = None


class WidgetPresetBindingOptionsRequest(BaseModel):
    source_id: str | None = None
    source_bot_id: str | None = None
    source_channel_id: uuid.UUID | None = None


class PinWidgetPresetRequest(BaseModel):
    dashboard_key: str | None = None
    config: dict | None = None
    source_bot_id: str | None = None
    source_channel_id: uuid.UUID | None = None
    display_label: str | None = None


def _pin_seed_from_layout_hints(layout_hints: dict | None) -> tuple[str | None, dict | None]:
    if not isinstance(layout_hints, dict):
        return None, None
    preferred_zone = layout_hints.get("preferred_zone")
    if not isinstance(preferred_zone, str) or not preferred_zone.strip():
        return None, None

    zone = preferred_zone.strip()
    min_cells = layout_hints.get("min_cells") if isinstance(layout_hints.get("min_cells"), dict) else {}
    max_cells = layout_hints.get("max_cells") if isinstance(layout_hints.get("max_cells"), dict) else {}

    def _cell_value(source: dict, key: str) -> int | None:
        value = source.get(key)
        if isinstance(value, int) and value > 0:
            return value
        return None

    if zone == "chip":
        return "header", {"x": 0, "y": 0, "w": 4, "h": 1}

    if zone == "header":
        width = 6
        height = 2
        min_w = _cell_value(min_cells, "w")
        min_h = _cell_value(min_cells, "h")
        max_w = _cell_value(max_cells, "w")
        max_h = _cell_value(max_cells, "h")
        if min_w is not None:
            width = max(width, min_w)
        if min_h is not None:
            height = max(height, min_h)
        if max_w is not None:
            width = min(width, max_w)
        if max_h is not None:
            height = min(height, max_h)
        return "header", {"x": 0, "y": 0, "w": width, "h": min(height, 2)}

    return zone, None


class WidgetConfigPatch(BaseModel):
    config: dict
    merge: bool = True


class PinSuiteRequest(BaseModel):
    suite_id: str
    dashboard_key: str
    source_bot_id: str | None = None
    source_channel_id: uuid.UUID | None = None
    members: list[str] | None = None


class LayoutItem(BaseModel):
    id: uuid.UUID
    x: int
    y: int
    w: int
    h: int
    # Optional chat-side zone for cross-canvas moves on channel dashboards.
    # Omit to keep the pin's current zone (same-canvas reorders). Allowed:
    # 'rail' | 'header' | 'dock' | 'grid'. Validation lives in
    # ``dashboard_pins._validate_layout_item`` so the error shape stays
    # consistent with the rest of the layout API.
    zone: str | None = None


class LayoutBulkRequest(BaseModel):
    items: list[LayoutItem]
    dashboard_key: str | None = None


class PinMetadataPatch(BaseModel):
    display_label: str | None = None


class PinScopePatch(BaseModel):
    # Explicit Optional[str] — ``null`` means "flip to user scope", a string
    # means "rescope to this bot." A separate endpoint (rather than folding
    # into PinMetadataPatch) avoids ambiguity between "field omitted" and
    # "field explicitly null" on the rename path.
    source_bot_id: str | None = None


@router.get(
    "/dashboard",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_dashboard_pins(
    slug: str = Query(default=DEFAULT_DASHBOARD_KEY),
    db: AsyncSession = Depends(get_db),
):
    """Return pins for ``slug`` (defaults to ``'default'``).

    Also records ``last_viewed_at`` on the dashboard so the redirect-target
    endpoint can send the user back to their most recent board. Channel
    dashboards (``channel:<uuid>``) are lazy-created on first read so a
    just-opened channel's side-panel can always fetch cleanly.
    """
    if is_channel_slug(slug):
        ch_id = slug[len(CHANNEL_SLUG_PREFIX):]
        # Raises 404 if the underlying channel doesn't exist.
        try:
            import uuid as _uuid
            _uuid.UUID(ch_id)
        except ValueError:
            raise HTTPException(400, f"Invalid channel slug: {slug}")
        await ensure_channel_dashboard(db, ch_id)

    # 404s if the dashboard doesn't exist (and isn't a channel slug).
    await get_dashboard(db, slug)
    pins = await list_pins(db, dashboard_key=slug)
    await touch_last_viewed(db, slug)
    return {"pins": [serialize_pin(p) for p in pins]}


@router.post(
    "/preview-for-tool",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def preview_dashboard_widget_for_tool(
    body: PreviewForToolRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.services.tool_execution import execute_tool_with_context
    from app.services.widget_preview import preview_active_widget_for_tool

    parsed_result, _raw = await execute_tool_with_context(
        body.tool_name,
        body.tool_args or {},
        bot_id=body.source_bot_id,
        channel_id=str(body.source_channel_id) if body.source_channel_id else None,
    )
    payload = (
        parsed_result
        if isinstance(parsed_result, dict)
        else {"result": parsed_result}
    )
    preview = await preview_active_widget_for_tool(
        db,
        tool_name=body.tool_name,
        sample_payload=payload,
        widget_config=body.widget_config,
        source_bot_id=body.source_bot_id,
        source_channel_id=str(body.source_channel_id) if body.source_channel_id else None,
    )
    return preview.model_dump(mode="json")


@router.get(
    "/presets",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def list_dashboard_widget_presets(
    include_binding_options: bool = Query(default=False),
    source_bot_id: str | None = Query(default=None),
    source_channel_id: uuid.UUID | None = Query(default=None),
):
    from app.services.widget_presets import (
        list_widget_presets,
        resolve_preset_binding_options,
        serialize_widget_preset,
    )

    presets = []
    for preset in list_widget_presets():
        row = serialize_widget_preset(preset)
        if include_binding_options:
            options_by_source, errors_by_source = await resolve_preset_binding_options(
                preset,
                source_bot_id=source_bot_id,
                source_channel_id=str(source_channel_id) if source_channel_id else None,
            )
            row["resolved_binding_options"] = options_by_source
            row["binding_source_errors"] = errors_by_source
        presets.append(row)
    return {"presets": presets}


@router.get(
    "/presets/{preset_id}",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_dashboard_widget_preset(
    preset_id: str,
):
    from app.services.widget_presets import get_widget_preset, serialize_widget_preset

    return serialize_widget_preset(get_widget_preset(preset_id))


@router.get(
    "/presets/{preset_id}/binding-options",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_dashboard_widget_preset_binding_options_query(
    preset_id: str,
    source_id: str = Query(..., description="Binding source id from the preset manifest."),
    source_bot_id: str | None = Query(default=None),
    source_channel_id: uuid.UUID | None = Query(default=None),
):
    from app.services.widget_presets import list_binding_options

    options = await list_binding_options(
        preset_id=preset_id,
        source_id=source_id,
        source_bot_id=source_bot_id,
        source_channel_id=str(source_channel_id) if source_channel_id else None,
    )
    return {"options": options}


@router.post(
    "/presets/{preset_id}/binding-options",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_dashboard_widget_preset_binding_options_body(
    preset_id: str,
    body: WidgetPresetBindingOptionsRequest,
):
    from app.services.widget_presets import list_binding_options

    if not body.source_id:
        raise HTTPException(400, "source_id is required")
    options = await list_binding_options(
        preset_id=preset_id,
        source_id=body.source_id,
        source_bot_id=body.source_bot_id,
        source_channel_id=str(body.source_channel_id) if body.source_channel_id else None,
    )
    return {"options": options}


@router.post(
    "/presets/{preset_id}/binding-options/{source_id}",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_dashboard_widget_preset_binding_options(
    preset_id: str,
    source_id: str,
    body: WidgetPresetBindingOptionsRequest,
):
    from app.services.widget_presets import list_binding_options

    options = await list_binding_options(
        preset_id=preset_id,
        source_id=source_id,
        source_bot_id=body.source_bot_id,
        source_channel_id=str(body.source_channel_id) if body.source_channel_id else None,
    )
    return {"options": options}


@router.post(
    "/presets/{preset_id}/preview",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def preview_dashboard_widget_preset(
    preset_id: str,
    body: WidgetPresetPreviewRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.services.widget_presets import preview_envelope_to_dict, preview_widget_preset

    preview, resolved_config, _tool_args = await preview_widget_preset(
        db,
        preset_id=preset_id,
        config=body.config,
        source_bot_id=body.source_bot_id,
        source_channel_id=str(body.source_channel_id) if body.source_channel_id else None,
    )
    return {
        "ok": preview.ok,
        "envelope": preview_envelope_to_dict(preview.envelope),
        "widget_contract": preview.widget_contract,
        "config_schema": preview.config_schema,
        "errors": [err.model_dump(mode="json") for err in preview.errors],
        "config": resolved_config,
    }


@router.post(
    "/presets/{preset_id}/pin",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def pin_dashboard_widget_preset(
    preset_id: str,
    body: PinWidgetPresetRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.services.widget_presets import (
        get_widget_preset,
        preview_envelope_to_dict,
        preview_widget_preset,
    )
    from app.services.widget_contracts import normalize_layout_hints

    preview, resolved_config, tool_args = await preview_widget_preset(
        db,
        preset_id=preset_id,
        config=body.config,
        source_bot_id=body.source_bot_id,
        source_channel_id=str(body.source_channel_id) if body.source_channel_id else None,
    )
    if not preview.ok or preview.envelope is None:
        raise HTTPException(400, f"Preset '{preset_id}' preview failed")

    preset = get_widget_preset(preset_id)
    tool_name = preset.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise HTTPException(400, f"Preset '{preset_id}' missing tool_name")
    preferred_zone, initial_grid_layout = _pin_seed_from_layout_hints(
        normalize_layout_hints(preset.get("layout_hints"))
    )

    envelope = preview_envelope_to_dict(preview.envelope)
    if isinstance(envelope, dict):
        envelope["source_instantiation_kind"] = "preset"
        envelope["source_preset_id"] = preset_id

    pin = await create_pin(
        db,
        source_kind="adhoc",
        tool_name=tool_name,
        envelope=envelope,
        source_channel_id=body.source_channel_id,
        source_bot_id=body.source_bot_id,
        tool_args=tool_args,
        widget_config=resolved_config,
        display_label=body.display_label,
        dashboard_key=body.dashboard_key or DEFAULT_DASHBOARD_KEY,
        zone=preferred_zone,
        grid_layout=initial_grid_layout,
    )
    return serialize_pin(pin)


@router.post(
    "/dashboard/pins",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def create_dashboard_pin(
    body: CreatePinRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new pin. Position is auto-assigned within the dashboard."""
    pin = await create_pin(
        db,
        source_kind=body.source_kind,
        tool_name=body.tool_name,
        envelope=body.envelope,
        source_channel_id=body.source_channel_id,
        source_bot_id=body.source_bot_id,
        tool_args=body.tool_args,
        widget_config=body.widget_config,
        display_label=body.display_label,
        dashboard_key=body.dashboard_key or DEFAULT_DASHBOARD_KEY,
        zone=body.zone,
        grid_layout=body.grid_layout,
    )
    logger.info(
        "Dashboard pin created: id=%s dashboard=%s tool=%s source=%s",
        pin.id, pin.dashboard_key, pin.tool_name, pin.source_kind,
    )
    return serialize_pin(pin)


@router.get(
    "/suites",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def list_suites():
    """List every discoverable widget suite on this server.

    Each suite is a widget folder under ``app/tools/local/widgets/`` or
    ``integrations/*/widgets/`` that contains a ``suite.yaml``. Members
    are the bundle slugs that declare ``db.shared: <suite_id>`` in their
    own ``widget.yaml``.
    """
    from app.services.widget_suite import scan_suites

    out = []
    for s in scan_suites():
        out.append({
            "suite_id": s.suite_id,
            "name": s.name,
            "description": s.description,
            "members": s.members,
            "schema_version": s.schema_version,
        })
    return {"suites": out}


@router.post(
    "/dashboard/pins/suite",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def pin_suite_endpoint(
    body: PinSuiteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Atomically pin every member of a suite onto a dashboard.

    Layout: each member appends below the existing pins via the standard
    ``_default_grid_layout(position)`` helper — same behavior as pinning a
    single widget repeatedly. Users rearrange from there.
    """
    from app.services.dashboard_pins import create_suite_pins

    pins = await create_suite_pins(
        db,
        suite_id=body.suite_id,
        dashboard_key=body.dashboard_key,
        source_bot_id=body.source_bot_id,
        source_channel_id=body.source_channel_id,
        member_slugs=body.members,
    )
    return {
        "pins": [serialize_pin(p) for p in pins],
        "suite_id": body.suite_id,
        "dashboard_key": body.dashboard_key,
    }


@router.get(
    "/dashboard/pins/{pin_id}/db-status",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def get_pin_db_status(
    pin_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Check whether the pin's widget bundle has a SQLite DB with content.

    Used by the unpin flow: the UI calls this first, and if ``has_content`` is
    True it surfaces a confirmation before deleting.

    Returns ``{has_content: false}`` for inline widgets and empty/absent DBs.
    """
    pin = await get_pin(db, pin_id)
    from app.services.dashboard_pins import check_pin_db_content
    info = await check_pin_db_content(pin)
    if info is None:
        return {"has_content": False}
    return info


@router.delete(
    "/dashboard/pins/{pin_id}",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def delete_dashboard_pin(
    pin_id: uuid.UUID,
    delete_bundle_data: bool = Query(
        default=False,
        description="When true, also unlinks the pin's bundle data.sqlite file.",
    ),
    db: AsyncSession = Depends(get_db),
):
    result = await delete_pin(db, pin_id, delete_bundle_data=delete_bundle_data)
    return {"ok": True, **result}


@router.patch(
    "/dashboard/pins/{pin_id}/config",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def patch_dashboard_pin_config(
    pin_id: uuid.UUID,
    body: WidgetConfigPatch,
    db: AsyncSession = Depends(get_db),
):
    return await apply_dashboard_pin_config_patch(
        db, pin_id, body.config, merge=body.merge,
    )


@router.patch(
    "/dashboard/pins/{pin_id}",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def patch_dashboard_pin_metadata(
    pin_id: uuid.UUID,
    body: PinMetadataPatch,
    db: AsyncSession = Depends(get_db),
):
    return await rename_pin(db, pin_id, body.display_label)


@router.patch(
    "/dashboard/pins/{pin_id}/scope",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def patch_dashboard_pin_scope(
    pin_id: uuid.UUID,
    body: PinScopePatch,
    db: AsyncSession = Depends(get_db),
):
    """Switch a pin between user-scope (``source_bot_id: null``) and
    bot-scope (``source_bot_id: "<bot_id>"``).

    Updates both the column and the envelope so the renderer's scope chip
    and the widget-token-mint path stay in lockstep. 404 if the named bot
    doesn't exist.
    """
    return await update_pin_scope(db, pin_id, body.source_bot_id)


@router.post(
    "/dashboard/pins/layout",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def patch_dashboard_pin_layout(
    body: LayoutBulkRequest,
    db: AsyncSession = Depends(get_db),
):
    """Bulk-commit grid coordinates after a drag/resize session.

    All ids must belong to ``body.dashboard_key`` (defaults to 'default');
    otherwise the whole call fails with 400 so we never commit a partial
    layout across dashboards.
    """
    slug = body.dashboard_key or DEFAULT_DASHBOARD_KEY
    items = [item.model_dump(mode="json") for item in body.items]
    return await apply_layout_bulk(db, items, dashboard_key=slug)


@router.post(
    "/dashboard/pins/{pin_id}/promote-panel",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def promote_dashboard_pin_to_panel(
    pin_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Make this pin the dashboard's main panel.

    Atomically clears any other panel pin in the same dashboard and flips
    ``grid_config.layout_mode`` to ``"panel"``. Other pins keep their grid
    coordinates and surface in the rail strip alongside the panel.
    """
    return await promote_pin_to_panel(db, pin_id)


@router.delete(
    "/dashboard/pins/{pin_id}/promote-panel",
    dependencies=[Depends(require_scopes("channels:write"))],
)
async def demote_dashboard_pin_from_panel(
    pin_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Clear ``is_main_panel`` on this pin.

    If this leaves the dashboard with no panel pin the layout mode reverts to
    ``"grid"`` so the dashboard renders as a normal RGL canvas again.
    """
    return await demote_pin_from_panel(db, pin_id)


@router.post(
    "/dashboard/pins/{pin_id}/refresh",
    dependencies=[Depends(require_scopes("channels:read"))],
)
async def refresh_dashboard_pin(
    pin_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Re-run the pin's state_poll and update its envelope.

    Imports the widget-actions internals lazily to avoid a module-level
    cycle (widget_actions may later import from here if we expose refresh
    helpers the other direction).
    """
    from app.routers.api_v1_widget_actions import (
        _do_state_poll,
        _evict_stale_cache,
        _resolve_tool_name,
        invalidate_poll_cache_for,
    )
    from app.services.widget_templates import get_state_poll_config

    _evict_stale_cache()
    pin = await get_pin(db, pin_id)
    resolved = _resolve_tool_name(pin.tool_name)
    poll_cfg = get_state_poll_config(resolved)
    if not poll_cfg:
        raise HTTPException(400, f"No state_poll config for {pin.tool_name}")

    # Force fresh call when the caller explicitly asked to refresh.
    invalidate_poll_cache_for(poll_cfg)
    envelope = await _do_state_poll(
        tool_name=resolved,
        display_label=pin.display_label or (pin.envelope or {}).get("display_label") or "",
        poll_cfg=poll_cfg,
        widget_config=pin.widget_config or {},
    )
    if envelope is None:
        raise HTTPException(502, "State poll failed to produce an envelope")

    env_dict = envelope.compact_dict()
    await update_pin_envelope(db, pin.id, env_dict)
    return {"ok": True, "envelope": env_dict}
