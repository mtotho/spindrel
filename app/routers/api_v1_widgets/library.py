"""Read-only widget content surface.

HTML widget catalog, library enumeration, manifests, and raw-content
serving. All endpoints are ``channels:read``; none mutate state.
"""
from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, require_scopes
from app.domain.errors import DomainError
from app.services.widget_themes import (
    BUILTIN_WIDGET_THEME_REF,
    active_widget_theme_ref,
    list_widget_themes,
    resolve_widget_theme,
)


logger = logging.getLogger(__name__)
router = APIRouter()


class WidgetThemeResolveOut(BaseModel):
    theme_ref: str
    explicit_channel_theme_ref: str | None = None
    global_theme_ref: str
    builtin_theme_ref: str = BUILTIN_WIDGET_THEME_REF
    theme: dict


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
    from app.services.html_widget_scanner import INTEGRATIONS_ROOT
    integration_dir = (INTEGRATIONS_ROOT / integration_id).resolve()
    # Guard against `..` or absolute integration_id escaping INTEGRATIONS_ROOT.
    try:
        integration_dir.relative_to(INTEGRATIONS_ROOT)
    except ValueError:
        raise HTTPException(404, "Integration not found")
    widgets_dir = str(integration_dir / "widgets")
    if not os.path.isdir(widgets_dir):
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
            shared_root = os.path.realpath(
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
            shared_root = os.path.realpath(
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
                shared_root = os.path.realpath(
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
    from app.services.widget_paths import scope_root
    from app.services.workspace import workspace_service
    from app.services.shared_workspace import shared_workspace_service
    from app.agent.bots import get_bot

    def _read(abs_path: str) -> dict:
        if not os.path.isfile(abs_path):
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
            except (HTTPException, DomainError):
                raise
            ws_root = workspace_service.get_workspace_root(bot_id, bot)
            if bot.shared_workspace_id:
                shared_root = os.path.realpath(
                    shared_workspace_service.get_host_root(bot.shared_workspace_id)
                )
        base = scope_root(scope, ws_root=ws_root, shared_root=shared_root)
        if not base:
            raise HTTPException(404, f"Scope {scope} unavailable.")
        bundle = os.path.join(base, name)
        for candidate in ("widget.yaml", "suite.yaml", "template.yaml"):
            p = os.path.join(bundle, candidate)
            if os.path.isfile(p):
                return _read(p)
        return {"manifest": None, "raw": None, "source_path": bundle}

    if scope == "integration":
        if not integration_id or not path:
            raise HTTPException(400, "integration_id + path required for integration scope.")
        # integration bundles: integrations/<id>/widgets/<path>; manifest sits
        # alongside index.html if present.
        integ_root = os.path.realpath(
            os.path.join(os.getcwd(), "integrations", integration_id, "widgets")
        )
        target_dir = os.path.dirname(os.path.realpath(os.path.join(integ_root, path)))
        if not target_dir.startswith(integ_root):
            raise HTTPException(400, "Invalid path.")
        manifest_path = os.path.join(target_dir, "widget.yaml")
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
        target_dir = os.path.dirname(os.path.realpath(os.path.join(ch_root, path)))
        if not target_dir.startswith(os.path.realpath(ch_root)):
            raise HTTPException(400, "Invalid path.")
        manifest_path = os.path.join(target_dir, "widget.yaml")
        return _read(manifest_path)

    raise HTTPException(400, f"Unknown scope: {scope}")


def _serve_widget_file(root: str, rel_path: str) -> dict:
    """Shared read-and-return body with path-traversal guards.

    Returns ``{path, content}`` to match the channel-workspace read endpoint
    shape so the renderer can dispatch without per-source body-shape branching.
    """
    root_real = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root, rel_path))
    if not (target == root_real or target.startswith(root_real + os.sep)):
        raise HTTPException(404, "File not found")
    if not os.path.isfile(target):
        raise HTTPException(404, "File not found")
    try:
        with open(target, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        raise HTTPException(404, "File not found")
    return {"path": rel_path, "content": content}
