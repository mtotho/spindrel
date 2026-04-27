"""Source-stamp helpers for pin contract drift detection.

Each origin kind has one canonical stamp — a short string written to
``WidgetDashboardPin.source_stamp`` at write/reconcile time. The hot read
path doesn't check the stamp; the background reconciler does. A stamp of
``None`` means "no live source exists; the snapshot is authoritative".

See ``~/.claude/plans/we-need-an-in-sparkling-sparrow.md`` §"Source stamps"
for the table of origin kind → stamp source.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from app.services.pin_contract.deps import ContractDeps, get_deps
from app.services.pin_contract.exceptions import (
    NativeSpecNotFound,
    PresetNotFound,
)

logger = logging.getLogger(__name__)


_NULL = b"\x00"


def _digest_files(paths: list[Path]) -> str | None:
    """sha256 of the concatenated contents of the given files.

    Missing files contribute ``b""`` between separators; if EVERY listed
    file is absent we return ``None`` (treat as "live source missing").
    """
    hasher = hashlib.sha256()
    found_any = False
    for i, path in enumerate(paths):
        if i > 0:
            hasher.update(_NULL)
        try:
            hasher.update(path.read_bytes())
            found_any = True
        except (OSError, FileNotFoundError):
            continue
    return hasher.hexdigest() if found_any else None


def _digest_obj(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def stamp_for_preset(preset_id: str) -> str | None:
    """Owning integration's content_hash. Reads from the integrations table.

    Presets are declared inside ``integration.yaml``, so the integration's
    content_hash is the right invalidation signal. Missing preset → ``None``
    → snapshot is authoritative (uninstalled-integration self-heal).
    """
    from app.services.integration_manifests import get_all_manifests

    deps = get_deps()
    try:
        preset = deps.presets.get(preset_id)
    except PresetNotFound:
        return None
    integration_id = preset.get("integration_id") or preset.get("source_integration_id")
    if not isinstance(integration_id, str) or not integration_id.strip():
        # Built-in / coreless presets have no integration → stamp the preset
        # body directly. Cheap; avoids needing a "core preset content_hash".
        return _digest_obj(preset)
    manifest = get_all_manifests().get(integration_id.strip())
    if not manifest:
        return None
    content_hash = manifest.get("content_hash")
    return content_hash if isinstance(content_hash, str) else None


def stamp_for_html_bundle(
    envelope: dict[str, Any],
    *,
    source_bot_id: str | None,
    deps: ContractDeps | None = None,
) -> str | None:
    """sha256(widget.yaml || NUL || html body) for any HTML widget bundle.

    One unified rule across every scope (integration / bot library /
    workspace library / channel-path / core). Returns ``None`` when the
    bundle directory cannot be resolved (uninstalled / deleted).
    """
    deps = deps or get_deps()
    bundle_dir = deps.html_manifests.resolve_bundle_dir(
        envelope, source_bot_id=source_bot_id,
    )
    if bundle_dir is None:
        return None
    paths = [bundle_dir / "widget.yaml"]
    source_path = envelope.get("source_path")
    if isinstance(source_path, str) and source_path.strip():
        # source_path is relative to the integration widgets root or channel
        # workspace root; the bundle dir is its parent. Use the basename as
        # the html body file name. Falls back to common defaults if no
        # explicit file name was supplied.
        rel = source_path.strip()
        body_name = Path(rel).name or "index.html"
    else:
        body_name = "index.html"
    paths.append(bundle_dir / body_name)
    return _digest_files(paths)


def stamp_for_tool_template(tool_name: str) -> str | None:
    """sha256 of the tool template registry entry.

    No new bookkeeping in ``widget_templates`` — we hash whatever
    ``get_widget_template`` returns. Equality-when-content-equal,
    deterministic, and naturally drift-detecting.
    """
    deps = get_deps()
    entry = deps.templates.get(tool_name)
    if entry is None:
        return None
    return _digest_obj(entry)


def stamp_for_native_instance(instance) -> str | None:
    """``state["updated_at"]`` if present, else sha256 of the state.

    NOT ``WidgetInstance.updated_at`` — that column has only a
    server_default and no onupdate, and native mutators write
    ``state["updated_at"]`` directly (e.g. standing_orders.py:373).
    """
    state = getattr(instance, "state", None)
    if not isinstance(state, dict):
        return None
    state_ts = state.get("updated_at")
    if isinstance(state_ts, str) and state_ts.strip():
        return state_ts.strip()
    return _digest_obj(state)


def stamp_for_native_widget_ref(widget_ref: str) -> str | None:
    """For a native pin where we have only the widget_ref (no instance row),
    stamp from the catalog spec body. The instance-bound stamp above is the
    primary; this is a fallback used by the resolver chain when invoked
    without a loaded instance.
    """
    deps = get_deps()
    try:
        spec = deps.natives.get(widget_ref)
    except NativeSpecNotFound:
        return None
    # NativeWidgetSpec is a dataclass; serialize a stable subset.
    payload = {
        "widget_ref": getattr(spec, "widget_ref", None),
        "config_schema": getattr(spec, "config_schema", None),
        "presentation_family": getattr(spec, "presentation_family", None),
        "panel_title": getattr(spec, "panel_title", None),
        "show_panel_title": getattr(spec, "show_panel_title", None),
        "layout_hints": getattr(spec, "layout_hints", None),
        "supported_scopes": list(getattr(spec, "supported_scopes", []) or []),
        "context_export": getattr(spec, "context_export", None),
    }
    return _digest_obj(payload)
