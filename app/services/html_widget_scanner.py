"""HTML widget catalog scanner.

Walks three widget sources and parses their frontmatter metadata so the
"Add widget" catalog can surface them with a clear provenance badge:

  - ``source="builtin"`` — ``app/tools/local/widgets/`` (ships with the repo)
  - ``source="integration"`` — ``<resolved integration>/<id>/widgets/``
  - ``source="channel"`` — ``<channel_workspace>/`` (user/bot-authored)

Files that a core ``widgets/<tool>/template.yaml`` or an integration's
``integration.yaml`` ``tool_widgets`` block references as
``html_template.path`` are **tool renderers**, not standalone catalog
entries, and are excluded from built-in / integration scans so they
don't double-surface in the Library.

Two discovery rules, union'd and de-duped:

  1. Any ``.html`` under a directory named ``widgets`` — canonical bundle
     convention (``data/widgets/<slug>/index.html``).
  2. Any ``.html`` anywhere in the channel workspace whose body references
     ``window.spindrel.`` or ``spindrel.`` — catches bot/user files outside
     convention. These get ``is_loose=True`` so the UI can badge them.

Parsed metadata comes from a leading HTML comment containing a YAML block:

    <!--
    ---
    name: Project status
    description: Live phase tracker
    version: 1.2.0
    tags: [dashboard, project]
    ---
    -->

Missing frontmatter is fine — sensible defaults fall back to the bundle slug.

If a ``widget.yaml`` file sits in the same directory as the scanned
``.html``, it is parsed and merged into the catalog entry — manifest
fields (``name``, ``description``, ``version``) take precedence over
HTML frontmatter.  The entry gains a ``has_manifest: True`` field so the
UI can badge backend-capable bundles.

Results are cached keyed by ``(channel_id, rel_path)`` with value
``(html_mtime, yaml_mtime, meta)``.  Either mtime mismatch triggers a
re-parse — no TTL needed.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from app.services.channel_workspace import get_channel_workspace_root

if TYPE_CHECKING:
    from app.agent.bots import BotConfig

# Repo roots for the non-channel sources.
# __file__ lives at app/services/html_widget_scanner.py.
# parents[0]=services, parents[1]=app, parents[2]=repo.
_REPO_ROOT = Path(__file__).resolve().parents[2]
BUILTIN_WIDGET_ROOT = (_REPO_ROOT / "app" / "tools" / "local" / "widgets").resolve()
# Compatibility constant for older tests/imports. Integration scans resolve
# through integrations.discovery so external/package roots use the same seam.
INTEGRATIONS_ROOT = (_REPO_ROOT / "integrations").resolve()

logger = logging.getLogger(__name__)

# Leading-HTML-comment YAML block. Tolerates leading whitespace, optional
# newline after the opening ``<!--``, and optional trailing newline before
# ``-->``.
_FRONTMATTER_RE = re.compile(
    r"^\s*<!--\s*\n?---\s*\n(.*?)\n---\s*\n?\s*-->",
    re.DOTALL,
)

_SPINDREL_TOKEN = "spindrel."

# Process-local cache: (channel_id, rel_path) -> (html_mtime, yaml_mtime | None, meta).
# Either mtime mismatch triggers re-parse. Cap at 2000 entries.
_SCAN_CACHE: dict[tuple[str, str], tuple[float, float | None, dict]] = {}
_CACHE_MAX = 2000


def parse_frontmatter(html: str) -> dict:
    """Extract the leading YAML frontmatter block.

    Returns ``{}`` for missing or malformed blocks — a bad block should
    never crash a whole scan.
    """
    if not html:
        return {}
    match = _FRONTMATTER_RE.match(html)
    if not match:
        return {}
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def has_spindrel_reference(html: str) -> bool:
    """Cheap substring check for ``spindrel.`` as a signal that the file is a
    widget (uses ``window.spindrel.api``/``callTool``/etc)."""
    if not html:
        return False
    return _SPINDREL_TOKEN in html


def _slug_from_path(rel_path: str) -> str:
    """Derive a display slug from the relative path.

    - ``data/widgets/project-status/index.html`` -> ``project-status``
    - ``data/widgets/gauge.html`` -> ``gauge``
    - ``notes/scratch.html`` -> ``scratch``
    """
    parent = os.path.basename(os.path.dirname(rel_path))
    stem = os.path.splitext(os.path.basename(rel_path))[0]
    if stem in ("index", "widget") and parent:
        return parent
    return stem


def _entry_from_metadata(
    rel_path: str,
    meta: dict,
    *,
    is_bundle: bool,
    is_loose: bool,
    size: int,
    mtime: float,
    has_manifest: bool = False,
    source: str = "channel",
    integration_id: str | None = None,
) -> dict:
    """Merge parsed frontmatter with path-derived defaults into a catalog entry.

    ``source`` distinguishes provenance for the catalog UI:
    ``"builtin"``, ``"integration"``, or ``"channel"``. ``integration_id``
    is set only when ``source == "integration"``.
    """
    slug = _slug_from_path(rel_path)
    name = meta.get("name") or slug
    display_label = meta.get("display_label") or name
    raw_panel_title = meta.get("panel_title")
    panel_title = str(raw_panel_title).strip() if isinstance(raw_panel_title, str) else ""
    raw_show_panel_title = meta.get("show_panel_title")
    raw_presentation_family = meta.get("presentation_family")
    presentation_family = (
        str(raw_presentation_family).strip().lower()
        if isinstance(raw_presentation_family, str)
        else "card"
    )
    tags = meta.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]

    extra_csp = meta.get("extra_csp")
    suite = meta.get("suite")
    package = meta.get("package")
    raw_runtime = meta.get("runtime")
    runtime = (
        str(raw_runtime).strip().lower()
        if isinstance(raw_runtime, str) and raw_runtime.strip()
        else "html"
    )
    if runtime not in {"html", "react"}:
        runtime = "html"
    group_kind: str | None = None
    group_ref: str | None = None
    if isinstance(suite, str) and suite.strip():
        group_kind = "suite"
        group_ref = suite.strip()
    elif isinstance(package, str) and package.strip():
        group_kind = "package"
        group_ref = package.strip()
    return {
        "path": rel_path,
        "slug": slug,
        "name": str(name),
        "description": str(meta.get("description") or ""),
        "display_label": str(display_label),
        "presentation_family": presentation_family if presentation_family in {"card", "chip", "panel"} else "card",
        "panel_title": panel_title or None,
        "show_panel_title": raw_show_panel_title if isinstance(raw_show_panel_title, bool) else None,
        "version": str(meta.get("version") or "0.0.0"),
        "author": meta.get("author") if meta.get("author") else None,
        "tags": [str(t) for t in tags],
        "icon": meta.get("icon") if meta.get("icon") else None,
        "is_bundle": is_bundle,
        "is_loose": is_loose,
        "has_manifest": has_manifest,
        "size": size,
        "modified_at": mtime,
        "source": source,
        "integration_id": integration_id,
        "extra_csp": extra_csp if isinstance(extra_csp, dict) else None,
        "widget_kind": "html",
        "widget_binding": "standalone",
        "theme_support": "html",
        "runtime": runtime,
        "group_kind": group_kind,
        "group_ref": group_ref,
        "context_export": meta.get("context_export") if isinstance(meta.get("context_export"), dict) else None,
    }


def _is_under_widgets_dir(rel_path: str) -> bool:
    """True if any segment of ``rel_path`` (excluding the filename) is ``widgets``."""
    parts = rel_path.replace("\\", "/").split("/")
    return "widgets" in parts[:-1]


def _cache_trim() -> None:
    """Drop arbitrary entries when over cap. Simple size bound — not LRU."""
    if len(_SCAN_CACHE) <= _CACHE_MAX:
        return
    over = len(_SCAN_CACHE) - _CACHE_MAX
    for key in list(_SCAN_CACHE.keys())[:over]:
        _SCAN_CACHE.pop(key, None)


def _yaml_path_for(abs_path: str) -> str:
    """Return the sibling ``widget.yaml`` path for an html file."""
    return os.path.join(os.path.dirname(abs_path), "widget.yaml")


def _scan_metadata_for(
    cache_scope: str,
    rel_path: str,
    abs_path: str,
    mtime: float,
    *,
    force_include: bool = False,
) -> dict | None:
    """Return cached metadata for this file, re-parsing if either mtime changed.

    Returns ``None`` if the file cannot be read or is not a recognizable
    widget (no ``widgets/`` parent AND no ``spindrel.`` reference). When
    ``force_include=True`` (built-in / integration scans whose root IS a
    widgets dir by definition) the heuristic gate is bypassed and the file
    is always treated as a widget.
    """
    yaml_path = _yaml_path_for(abs_path)
    try:
        yaml_mtime: float | None = os.stat(yaml_path).st_mtime
    except OSError:
        yaml_mtime = None

    cache_key = (cache_scope, rel_path)
    cached = _SCAN_CACHE.get(cache_key)
    if cached and cached[0] == mtime and cached[1] == yaml_mtime:
        return cached[2]

    try:
        with open(abs_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        _SCAN_CACHE.pop(cache_key, None)
        return None

    is_bundle = _is_under_widgets_dir(rel_path) or force_include
    has_ref = has_spindrel_reference(content)
    if not force_include and not is_bundle and not has_ref:
        # Not a widget. Cache the negative result so we don't re-read next scan.
        _SCAN_CACHE[cache_key] = (mtime, yaml_mtime, {})
        _cache_trim()
        return {}

    meta = parse_frontmatter(content)
    meta["__is_bundle"] = is_bundle
    meta["__is_loose"] = has_ref and not is_bundle and not force_include
    meta["__has_manifest"] = False

    if yaml_mtime is not None:
        # Manifest fields take precedence over HTML frontmatter.
        try:
            from app.services.widget_manifest import parse_manifest, ManifestError

            manifest = parse_manifest(yaml_path)
            meta["name"] = manifest.name
            meta["description"] = manifest.description
            meta["version"] = manifest.version
            meta["presentation_family"] = manifest.presentation_family
            if manifest.suite:
                meta["suite"] = manifest.suite
                meta.pop("package", None)
            if manifest.package:
                meta["package"] = manifest.package
                meta.pop("suite", None)
            if manifest.panel_title is not None:
                meta["panel_title"] = manifest.panel_title
            if manifest.show_panel_title is not None:
                meta["show_panel_title"] = manifest.show_panel_title
            if manifest.context_export is not None:
                meta["context_export"] = manifest.context_export
            meta["__has_manifest"] = True
            if manifest.extra_csp:
                meta["extra_csp"] = manifest.extra_csp
            if manifest.config_schema:
                meta["config_schema"] = manifest.config_schema
        except (ManifestError, Exception) as exc:
            logger.warning("widget.yaml at %s failed validation: %s", yaml_path, exc)

    _SCAN_CACHE[cache_key] = (mtime, yaml_mtime, meta)
    _cache_trim()
    return meta


def scan_channel(channel_id: str, bot: "BotConfig") -> list[dict]:
    """Walk the channel workspace for HTML widgets and return catalog entries.

    Safe against missing workspace directories. Skips symlinks and files
    outside the workspace root.
    """
    ws_path = get_channel_workspace_root(channel_id, bot)
    if not os.path.isdir(ws_path):
        return []

    ws_real = os.path.realpath(ws_path)
    entries: list[dict] = []

    for dirpath, dirnames, filenames in os.walk(ws_path, followlinks=False):
        # Skip hidden dirs (.versions, .git, .channel_info, etc.)
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]

        for filename in filenames:
            if not filename.endswith(".html"):
                continue
            abs_path = os.path.join(dirpath, filename)
            # Guard against symlinks escaping the workspace.
            real = os.path.realpath(abs_path)
            if not (real == ws_real or real.startswith(ws_real + os.sep)):
                continue
            if os.path.islink(abs_path):
                continue

            try:
                stat = os.stat(abs_path)
            except OSError:
                continue

            rel_path = os.path.relpath(abs_path, ws_path).replace("\\", "/")
            meta = _scan_metadata_for(channel_id, rel_path, abs_path, stat.st_mtime)
            if not meta:  # None (unreadable) or {} (not a widget)
                continue

            is_bundle = meta.get("__is_bundle", False)
            is_loose = meta.get("__is_loose", False)
            has_manifest = meta.get("__has_manifest", False)
            # Strip internal markers before building the public entry.
            public_meta = {k: v for k, v in meta.items() if not k.startswith("__")}
            entries.append(
                _entry_from_metadata(
                    rel_path,
                    public_meta,
                    is_bundle=is_bundle,
                    is_loose=is_loose,
                    has_manifest=has_manifest,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    source="channel",
                )
            )

    # Stable ordering: bundles first, then loose. Within each group,
    # alphabetical by name.
    entries.sort(key=lambda e: (not e["is_bundle"], e["name"].lower()))
    return entries


# ---------------------------------------------------------------------------
# Tool-renderer exclusion set
# ---------------------------------------------------------------------------
#
# Files referenced as ``html_template.path`` by a core
# ``widgets/<tool>/template.yaml`` or an integration's ``tool_widgets``
# block are tool renderers — they render a specific tool's output and are
# already surfaced in the Library under the "Tool renderers" section. They
# must NOT also appear in the standalone widget catalog.

def _collect_tool_renderer_paths() -> set[str]:
    """Return absolute paths of every HTML file registered as a tool renderer.

    Two sources:
      - ``<BUILTIN_WIDGET_ROOT>/<tool>/template.yaml`` —
        ``html_template.path`` resolved against the per-tool widget folder.
      - ``integrations/<id>/integration.yaml`` — each
        ``tool_widgets.<tool>.html_template.path`` resolved against
        ``integrations/<id>/``.

    Failures reading/parsing a single file are logged and skipped so a
    malformed yaml never poisons the catalog scan.
    """
    paths: set[str] = set()

    # Built-in tool renderers: widgets/<tool>/template.yaml.
    if BUILTIN_WIDGET_ROOT.is_dir():
        for entry in BUILTIN_WIDGET_ROOT.iterdir():
            if not entry.is_dir():
                continue
            yaml_path = entry / "template.yaml"
            if yaml_path.is_file():
                paths.update(_extract_html_template_paths(yaml_path, entry))

    # Per-integration tool renderers live under each resolved integration root.
    from integrations.discovery import iter_integration_sources

    for source in iter_integration_sources():
        yaml_path = source.path / "integration.yaml"
        if yaml_path.is_file():
            paths.update(_extract_html_template_paths(yaml_path, source.path))

    return paths


def _extract_html_template_paths(yaml_path: Path, base_dir: Path) -> set[str]:
    """Parse a widget yaml and return absolute html_template paths it references.

    Handles three shapes:
      - Core ``widgets/<tool>/template.yaml``: top-level IS the widget_def
        (``{html_template: {path: ...}, ...}``).
      - Integration yaml: ``{tool_widgets: {<tool>: widget_def, ...}}``.
      - Legacy/compat: ``{<tool>: widget_def, ...}``.
    """
    try:
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Could not parse %s for tool-renderer exclusions: %s", yaml_path, exc)
        return set()
    if not isinstance(data, dict):
        return set()

    # Unwrapped widget_def: top-level has widget fields directly.
    if "html_template" in data or "template" in data:
        widget_defs = [data]
    elif "tool_widgets" in data and isinstance(data["tool_widgets"], dict):
        widget_defs = list(data["tool_widgets"].values())
    else:
        widget_defs = list(data.values())

    out: set[str] = set()
    for widget_def in widget_defs:
        if not isinstance(widget_def, dict):
            continue
        html_template = widget_def.get("html_template")
        if not isinstance(html_template, dict):
            continue
        rel = html_template.get("path")
        if not rel or not isinstance(rel, str):
            continue
        abs_path = (base_dir / rel).resolve()
        out.add(str(abs_path))
    return out


def _walk_standalone_html(
    root: Path,
    *,
    cache_scope: str,
    source: str,
    integration_id: str | None,
    excluded_abs_paths: set[str],
) -> list[dict]:
    """Shared walker for the non-channel sources (builtin + integration).

    Honors the same two discovery rules as ``scan_channel`` (``widgets/``
    parent OR ``spindrel.`` reference) plus a tool-renderer exclusion set
    so we don't double-surface templates already shown under "Tool renderers".
    """
    if not root.is_dir():
        return []

    root_real = os.path.realpath(root)
    entries: list[dict] = []

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "node_modules"]

        for filename in filenames:
            if not filename.endswith(".html"):
                continue
            abs_path = os.path.join(dirpath, filename)
            real = os.path.realpath(abs_path)
            if not (real == root_real or real.startswith(root_real + os.sep)):
                continue
            if os.path.islink(abs_path):
                continue
            if real in excluded_abs_paths:
                continue

            try:
                stat = os.stat(abs_path)
            except OSError:
                continue

            rel_path = os.path.relpath(abs_path, root).replace("\\", "/")
            meta = _scan_metadata_for(
                cache_scope, rel_path, abs_path, stat.st_mtime, force_include=True,
            )
            if not meta:
                continue

            is_bundle = meta.get("__is_bundle", False)
            is_loose = meta.get("__is_loose", False)
            has_manifest = meta.get("__has_manifest", False)
            public_meta = {k: v for k, v in meta.items() if not k.startswith("__")}
            entries.append(
                _entry_from_metadata(
                    rel_path,
                    public_meta,
                    is_bundle=is_bundle,
                    is_loose=is_loose,
                    has_manifest=has_manifest,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    source=source,
                    integration_id=integration_id,
                )
            )

    entries.sort(key=lambda e: (not e["is_bundle"], e["name"].lower()))
    return entries


def scan_builtin() -> list[dict]:
    """Walk ``app/tools/local/widgets/`` and return catalog entries for every
    standalone HTML widget (excluding tool renderers)."""
    excluded = _collect_tool_renderer_paths()
    return _walk_standalone_html(
        BUILTIN_WIDGET_ROOT,
        cache_scope="__builtin__",
        source="builtin",
        integration_id=None,
        excluded_abs_paths=excluded,
    )


def scan_integration(integration_id: str) -> list[dict]:
    """Walk a resolved integration's ``widgets/`` dir for standalone widgets.

    Returns an empty list when the integration has no widgets dir. Tool
    renderers referenced by the integration's ``tool_widgets`` block are
    excluded.
    """
    from integrations.discovery import find_integration_source

    source = find_integration_source(integration_id)
    if source is None:
        return []
    widgets_dir = source.path / "widgets"
    excluded = _collect_tool_renderer_paths()
    return _walk_standalone_html(
        widgets_dir,
        cache_scope=f"__integration__:{source.integration_id}",
        source="integration",
        integration_id=source.integration_id,
        excluded_abs_paths=excluded,
    )


def scan_all_integrations() -> list[tuple[str, list[dict]]]:
    """Walk every integration directory. Returns ``[(integration_id, entries), ...]``
    sorted by integration_id. Integrations with zero standalone widgets are
    omitted so the caller can render a compact list."""
    from integrations.discovery import iter_integration_sources

    excluded = _collect_tool_renderer_paths()
    out: list[tuple[str, list[dict]]] = []
    for source in sorted(iter_integration_sources(), key=lambda s: s.integration_id):
        widgets_dir = source.path / "widgets"
        if not widgets_dir.is_dir():
            continue
        entries = _walk_standalone_html(
            widgets_dir,
            cache_scope=f"__integration__:{source.integration_id}",
            source="integration",
            integration_id=source.integration_id,
            excluded_abs_paths=excluded,
        )
        if entries:
            out.append((source.integration_id, entries))
    return out


def invalidate_cache(scope: str | None = None) -> None:
    """Drop cached metadata. Without a scope, clears everything.

    ``scope`` matches the first element of the cache key — either a
    channel uuid (for channel scans) or one of the sentinel values
    ``"__builtin__"`` / ``"__integration__:<id>"``.
    """
    if scope is None:
        _SCAN_CACHE.clear()
        return
    for key in list(_SCAN_CACHE.keys()):
        if key[0] == scope:
            _SCAN_CACHE.pop(key, None)
