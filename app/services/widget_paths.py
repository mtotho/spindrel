"""Widget library virtual-path (``widget://``) resolution.

Bots author widgets via existing file ops over a virtual URI namespace
rather than juggling filesystem paths.  Three scopes:

- ``widget://core/<name>/...``      → in-repo ``app/tools/local/widgets/<name>/...``
                                      (shipped with the server, read-only at runtime)
- ``widget://bot/<name>/...``       → ``<ws_root>/.widget_library/<name>/...``
                                      (this bot's private library)
- ``widget://workspace/<name>/...`` → ``<shared_root>/.widget_library/<name>/...``
                                      (shared by all bots in the workspace —
                                      requires a shared workspace)

Each bundle's inner boundary is the ``<name>/`` directory; traversal to
sibling bundles or out of the library root is rejected.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# Core (in-repo) library dir.  Lives alongside the widget-related tool
# modules under ``app/tools/local/widgets/``.
CORE_WIDGETS_DIR = str(Path(__file__).resolve().parent.parent / "tools" / "local" / "widgets")

# Per-bot and per-workspace libraries live under a hidden dir inside the
# corresponding workspace root so they ride along with normal workspace
# persistence without polluting the bot's visible file tree.
WIDGET_LIBRARY_DIRNAME = ".widget_library"

# widget://<scope>[/<name>[/<rest>]]
# Name group is intentionally permissive — concrete charset validation runs
# through ``_NAME_RE`` so the caller gets a precise "Invalid widget name"
# error instead of a generic URI-format rejection.
WIDGET_URI_RE = re.compile(
    r"^widget://(core|bot|workspace)(?:/([^/]+))?(?:/(.*))?$"
)
_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

SCOPES = ("core", "bot", "workspace")


def is_widget_uri(path: str) -> bool:
    """Cheap prefix test — cheaper than running the full regex."""
    return path.startswith("widget://")


def scope_root(
    scope: str, *, ws_root: str | None, shared_root: str | None
) -> str | None:
    """Return the on-disk root directory for a scope, or ``None`` if unavailable.

    - ``core`` → always available.
    - ``bot`` → requires ``ws_root``.
    - ``workspace`` → requires ``shared_root`` (shared-workspace bots only).
    """
    if scope == "core":
        return CORE_WIDGETS_DIR
    if scope == "bot":
        if not ws_root:
            return None
        return os.path.join(ws_root, WIDGET_LIBRARY_DIRNAME)
    if scope == "workspace":
        if not shared_root:
            return None
        return os.path.join(shared_root, WIDGET_LIBRARY_DIRNAME)
    return None


def resolve_widget_uri(
    uri: str, *, ws_root: str | None, shared_root: str | None
) -> tuple[str, str, str, bool]:
    """Resolve a ``widget://`` URI to an absolute host path.

    Returns ``(abs_path, scope, name, read_only)``.  ``read_only`` is True
    for the ``core`` scope (in-repo library is version-controlled, not
    writable at runtime).

    Raises ``ValueError`` on malformed URIs, unknown scopes, invalid names,
    missing shared-workspace context, or path traversal out of the bundle.
    """
    uri = uri.strip()
    m = WIDGET_URI_RE.match(uri)
    if not m:
        raise ValueError(f"Invalid widget:// URI: {uri}")

    scope = m.group(1)
    name = m.group(2)
    rest = m.group(3) or ""

    if not name:
        raise ValueError(
            f"widget:// URI must include a widget name "
            f"(e.g. widget://{scope}/<name>/index.html)."
        )
    if not _NAME_RE.match(name):
        raise ValueError(
            f"Invalid widget name '{name}'. Names must be letters, digits, '_', or '-'."
        )

    base_dir = scope_root(scope, ws_root=ws_root, shared_root=shared_root)
    if base_dir is None:
        if scope == "workspace":
            raise ValueError(
                "widget://workspace/... requires a shared workspace — this bot "
                "has none. Use widget://bot/... for bot-private widgets."
            )
        raise ValueError(f"widget:// scope '{scope}' unavailable in this context.")

    bundle_dir = os.path.join(base_dir, name)
    target = os.path.join(bundle_dir, rest) if rest else bundle_dir

    # Traversal guard — compare realpath of target against realpath of bundle.
    # realpath handles non-existent trailing segments fine (a new widget file
    # being written for the first time).
    bundle_real = os.path.realpath(bundle_dir)
    target_real = os.path.realpath(target)
    if not (target_real == bundle_real or target_real.startswith(bundle_real + os.sep)):
        raise ValueError(f"widget:// path escapes bundle: {uri}")

    return target_real, scope, name, scope == "core"
