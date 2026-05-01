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
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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


@dataclass(frozen=True)
class WidgetScopePolicy:
    scope: Literal["core", "bot", "workspace"]
    root_kind: Literal["repo_core_library", "bot_private_library", "shared_workspace_library"]
    read_only: bool
    requires_shared_root: bool
    sharing_model: Literal["server_shipped", "bot_private", "workspace_shared_library"]


def widget_scope_policy(scope: str) -> WidgetScopePolicy:
    """Return the explicit security policy for a widget URI scope."""
    if scope == "core":
        return WidgetScopePolicy(
            scope="core",
            root_kind="repo_core_library",
            read_only=True,
            requires_shared_root=False,
            sharing_model="server_shipped",
        )
    if scope == "bot":
        return WidgetScopePolicy(
            scope="bot",
            root_kind="bot_private_library",
            read_only=False,
            requires_shared_root=False,
            sharing_model="bot_private",
        )
    if scope == "workspace":
        return WidgetScopePolicy(
            scope="workspace",
            root_kind="shared_workspace_library",
            read_only=False,
            requires_shared_root=True,
            sharing_model="workspace_shared_library",
        )
    raise ValueError(f"Unknown widget:// scope: {scope}")


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
    policy = widget_scope_policy(scope)
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

    # Symlink rejection — a bot with shell access could ``ln -s /etc
    # /workspace/.widget_library/foo`` to make their own bundle root a
    # symlink. The realpath comparison above passes in that case (both ends
    # resolve through the link), so we additionally walk every existing
    # path component from the library root down and reject if any segment
    # is a symlink. ``base_real`` (the library root) is intentionally
    # checked too — a symlinked library root is just as load-bearing as a
    # symlinked bundle dir. A non-existent trailing segment (writing a new
    # file) is fine; we stop walking when a component doesn't yet exist.
    base_real = os.path.realpath(base_dir)
    _reject_symlink_components(target, base_dir=base_dir, uri=uri)
    if base_real != base_dir and os.path.islink(base_dir):
        raise ValueError(f"widget:// library root is a symlink: {base_dir}")

    return target_real, scope, name, policy.read_only


def _reject_symlink_components(
    target: str, *, base_dir: str, uri: str,
) -> None:
    """Walk ``target`` component-by-component starting at ``base_dir`` and
    raise if any existing path segment is a symlink.

    Stops walking on the first non-existent component, which means writing
    a new file (``widget://bot/foo/new_file.html``) is allowed — only the
    parent dirs that already exist are checked.
    """
    rel = os.path.relpath(target, base_dir)
    if rel == os.curdir:
        return
    parts = [p for p in rel.split(os.sep) if p and p != os.curdir]
    walk = base_dir
    for part in parts:
        if part == os.pardir:
            # The realpath-based traversal guard above already rejects
            # ``..`` segments that escape the bundle; defensive bail-out.
            raise ValueError(f"widget:// path contains '..': {uri}")
        walk = os.path.join(walk, part)
        if not os.path.lexists(walk):
            return
        if os.path.islink(walk):
            raise ValueError(
                f"widget:// path contains a symlink at {walk!r}; "
                "symlinks inside widget bundles are rejected."
            )
