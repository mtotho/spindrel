"""HTML widget workspace scanner.

Walks a channel workspace for standalone HTML widgets and parses their
frontmatter metadata so they can be surfaced in the "Add widget" catalog.

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
from typing import TYPE_CHECKING, Any

import yaml

from app.services.channel_workspace import get_channel_workspace_root

if TYPE_CHECKING:
    from app.agent.bots import BotConfig

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
) -> dict:
    """Merge parsed frontmatter with path-derived defaults into a catalog entry."""
    slug = _slug_from_path(rel_path)
    name = meta.get("name") or slug
    display_label = meta.get("display_label") or name
    tags = meta.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]

    return {
        "path": rel_path,
        "slug": slug,
        "name": str(name),
        "description": str(meta.get("description") or ""),
        "display_label": str(display_label),
        "version": str(meta.get("version") or "0.0.0"),
        "author": meta.get("author") if meta.get("author") else None,
        "tags": [str(t) for t in tags],
        "icon": meta.get("icon") if meta.get("icon") else None,
        "is_bundle": is_bundle,
        "is_loose": is_loose,
        "has_manifest": has_manifest,
        "size": size,
        "modified_at": mtime,
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
    channel_id: str,
    rel_path: str,
    abs_path: str,
    mtime: float,
) -> dict | None:
    """Return cached metadata for this file, re-parsing if either mtime changed.

    Returns ``None`` if the file cannot be read or is not a recognizable
    widget (no ``widgets/`` parent AND no ``spindrel.`` reference).
    """
    yaml_path = _yaml_path_for(abs_path)
    try:
        yaml_mtime: float | None = os.stat(yaml_path).st_mtime
    except OSError:
        yaml_mtime = None

    cache_key = (channel_id, rel_path)
    cached = _SCAN_CACHE.get(cache_key)
    if cached and cached[0] == mtime and cached[1] == yaml_mtime:
        return cached[2]

    try:
        with open(abs_path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        _SCAN_CACHE.pop(cache_key, None)
        return None

    is_bundle = _is_under_widgets_dir(rel_path)
    has_ref = has_spindrel_reference(content)
    if not is_bundle and not has_ref:
        # Not a widget. Cache the negative result so we don't re-read next scan.
        _SCAN_CACHE[cache_key] = (mtime, yaml_mtime, {})
        _cache_trim()
        return {}

    meta = parse_frontmatter(content)
    meta["__is_bundle"] = is_bundle
    meta["__is_loose"] = has_ref and not is_bundle
    meta["__has_manifest"] = False

    if yaml_mtime is not None:
        # Manifest fields take precedence over HTML frontmatter.
        try:
            from app.services.widget_manifest import parse_manifest, ManifestError

            manifest = parse_manifest(yaml_path)
            meta["name"] = manifest.name
            meta["description"] = manifest.description
            meta["version"] = manifest.version
            meta["__has_manifest"] = True
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
                )
            )

    # Stable ordering: bundles first, then loose. Within each group,
    # alphabetical by name.
    entries.sort(key=lambda e: (not e["is_bundle"], e["name"].lower()))
    return entries


def invalidate_cache(channel_id: str | None = None) -> None:
    """Drop cached metadata. Without ``channel_id``, clears everything."""
    if channel_id is None:
        _SCAN_CACHE.clear()
        return
    for key in list(_SCAN_CACHE.keys()):
        if key[0] == channel_id:
            _SCAN_CACHE.pop(key, None)
