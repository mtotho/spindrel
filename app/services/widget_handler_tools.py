"""Dynamic widget-handler tool source — bot-callable bridge.

Widgets can opt-in handlers to be invoked from a bot's turn by adding a
``handlers:`` block to their ``widget.yaml`` with ``bot_callable: true``.
This module walks the pins visible to ``(bot_id, channel_id)``, parses
each pin's manifest, and yields an OpenAI function-call schema per
bot-callable handler named ``widget__<slug>__<handler>``.

Dispatch path: the LLM calls the tool, ``tool_dispatch`` recognises the
``widget__``-prefix, this module's :func:`resolve_widget_handler` looks up
``(pin, handler_name)`` by tool name, and ``widget_py.invoke_action`` runs
the handler under the pin's ``source_bot_id`` (same identity flow as the
iframe). The calling bot's scopes never widen the handler — the pin's bot
is the ceiling, matching the existing "widget runs as its bot" invariant.

Tool names are restricted to ``[a-zA-Z0-9_-]`` by OpenAI/Gemini function
schemas, so ``__`` is the separator (dots + tildes both reject).

Read-side visibility rules:

* Pins on the caller's channel dashboard (``channel:<channel_id>``).
* Pins on any dashboard whose ``source_bot_id`` matches the calling bot
  (``global:<slug>``, ``user:<id>`` — anywhere the bot itself owns).

Global/cross-bot visibility expansion is a deliberate follow-up: when a
bot should read another bot's widget state, the right answer is a scope
grant on the dashboard, not a special case here.
"""
from __future__ import annotations

import hashlib
import logging
import re
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_, select

from app.db.models import WidgetDashboardPin
from app.services.widget_manifest import HandlerSpec, ManifestError, parse_manifest

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


TOOL_NAME_PREFIX = "widget__"
TOOL_NAME_SEP = "__"

# Same character class as manifest handler names + dashes for slugs.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _safe_slug(name: str) -> str:
    """Normalize a manifest name into a tool-name fragment.

    We can't trust the raw ``manifest.name`` (``"MC Tasks"``) — tool names
    must be grep-safe identifiers drawn from ``[a-zA-Z0-9_-]``. Lowercase,
    spaces → ``-``, underscores → ``-`` (the ``__`` separator owns that
    character), drop everything else, bound to 48 chars. Empty or
    all-stripped names fall back to ``"widget"`` so we never emit
    ``widget____add_todo``.
    """
    s = name.strip().lower().replace(" ", "-").replace("_", "-")
    s = re.sub(r"[^a-z0-9-]+", "", s)
    s = s.strip("-")[:48]
    return s or "widget"


def _pin_hash(pin_id) -> str:
    """Short deterministic hash of a pin id for disambiguation suffixes."""
    return hashlib.sha1(str(pin_id).encode("utf-8")).hexdigest()[:6]


def _load_manifest_safely(pin: WidgetDashboardPin):
    """Return ``(manifest, bundle_dir)`` or ``(None, None)`` on any failure.

    A pin without a widget.yaml, a malformed yaml, or a pin for an inline
    (non-path-mode) envelope has no handler surface. We log-and-skip
    rather than fail the turn — one broken pin shouldn't poison the whole
    tool pool.
    """
    from app.services.widget_py import resolve_bundle_dir

    try:
        bundle_dir = resolve_bundle_dir(pin)
    except (ValueError, FileNotFoundError) as exc:
        logger.debug("widget handler scan: skipping pin %s (bundle: %s)", pin.id, exc)
        return None, None

    yaml_path = bundle_dir / "widget.yaml"
    if not yaml_path.is_file():
        return None, bundle_dir
    try:
        return parse_manifest(yaml_path), bundle_dir
    except (ManifestError, OSError) as exc:
        logger.warning(
            "widget handler scan: pin %s has invalid widget.yaml (%s)", pin.id, exc,
        )
        return None, bundle_dir


def _build_tool_schema(
    tool_name: str,
    spec: HandlerSpec,
    manifest_name: str,
) -> dict[str, Any]:
    """Assemble an OpenAI function schema from a :class:`HandlerSpec`.

    ``args`` in the manifest is a ``{name: {type, description, required?}}``
    mapping; the OpenAI schema wants ``{properties: {...}, required: [...]}``.
    """
    props: dict[str, Any] = {}
    required: list[str] = []
    for arg_name, arg_spec in (spec.args or {}).items():
        prop = {k: v for k, v in arg_spec.items() if k != "required"}
        if "type" not in prop:
            prop["type"] = "string"
        props[arg_name] = prop
        if arg_spec.get("required"):
            required.append(arg_name)

    # Lead the description with the widget's display name so the LLM has
    # unambiguous context when multiple widgets declare similar handlers.
    description = (spec.description or "").strip()
    prefix = f"[{manifest_name}] " if manifest_name else ""
    full_description = f"{prefix}{description}".strip() or f"{manifest_name} handler"

    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": full_description,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required,
            },
        },
    }


async def _fetch_visible_pins(
    db: "AsyncSession",
    bot_id: str | None,
    channel_id: str | None,
) -> list[WidgetDashboardPin]:
    """Return pins the caller can see for handler enumeration.

    Channel pins: always included for the caller's current channel.
    Bot pins: any dashboard entry the calling bot authored — reaches
    ``global:*`` / ``user:*`` dashboards the bot pinned from prior turns.
    """
    clauses = []
    if channel_id:
        clauses.append(WidgetDashboardPin.dashboard_key == f"channel:{channel_id}")
    if bot_id:
        clauses.append(WidgetDashboardPin.source_bot_id == bot_id)
    if not clauses:
        return []

    q = (
        select(WidgetDashboardPin)
        .where(or_(*clauses))
        .order_by(WidgetDashboardPin.position.asc())
    )
    return list((await db.execute(q)).scalars().all())


async def list_widget_handler_tools(
    db: "AsyncSession",
    bot_id: str | None,
    channel_id: str | None,
) -> tuple[list[dict[str, Any]], dict[str, tuple[WidgetDashboardPin, str, str]]]:
    """Enumerate bot-callable widget handlers visible to ``(bot_id, channel_id)``.

    Returns ``(schemas, resolver_map)`` where ``resolver_map`` maps
    ``tool_name -> (pin, handler_name, safety_tier)`` — the dispatch path
    uses it to look up the pin at call time without re-parsing manifests.
    """
    if not bot_id and not channel_id:
        return [], {}

    pins = await _fetch_visible_pins(db, bot_id, channel_id)
    if not pins:
        return [], {}

    schemas: list[dict[str, Any]] = []
    resolver: dict[str, tuple[WidgetDashboardPin, str, str]] = {}
    name_counts: dict[str, int] = {}

    # First pass — assemble "preferred" names from the pin's manifest slug.
    # We collide-detect so two pins of the same widget on the same view get
    # deterministic suffixes instead of silently overwriting each other.
    candidates: list[tuple[WidgetDashboardPin, str, HandlerSpec, str]] = []
    for pin in pins:
        manifest, _ = _load_manifest_safely(pin)
        if manifest is None or not manifest.handlers:
            continue
        slug = _safe_slug(manifest.name)
        for spec in manifest.handlers:
            if not spec.bot_callable:
                continue
            base = f"{TOOL_NAME_PREFIX}{slug}{TOOL_NAME_SEP}{spec.name}"
            candidates.append((pin, slug, spec, base))
            name_counts[base] = name_counts.get(base, 0) + 1

    for pin, slug, spec, base in candidates:
        if name_counts[base] > 1:
            tool_name = f"{base}{TOOL_NAME_SEP}{_pin_hash(pin.id)}"
        else:
            tool_name = base
        manifest_name = pin.display_label or slug
        schema = _build_tool_schema(tool_name, spec, manifest_name)
        schemas.append(schema)
        resolver[tool_name] = (pin, spec.name, spec.safety_tier)

    return schemas, resolver


async def resolve_widget_handler(
    db: "AsyncSession",
    tool_name: str,
    bot_id: str | None,
    channel_id: str | None,
) -> tuple[WidgetDashboardPin, str, str] | None:
    """Inverse lookup — ``tool_name -> (pin, handler_name, safety_tier)``.

    Re-runs the visibility enumeration so the dispatch path can't be
    tricked by a stale resolver map from a different channel context.
    Returns ``None`` when the tool doesn't resolve (pin deleted between
    tool-list assembly and dispatch, or the name is malformed).
    """
    if not tool_name.startswith(TOOL_NAME_PREFIX):
        return None
    _, resolver = await list_widget_handler_tools(db, bot_id, channel_id)
    return resolver.get(tool_name)


def is_widget_handler_tool_name(name: str) -> bool:
    """True if ``name`` is in the ``widget__<slug>__<handler>`` namespace."""
    if not name.startswith(TOOL_NAME_PREFIX):
        return False
    # Must contain the slug/handler separator after the prefix, yielding
    # ``widget__<slug>__<handler>[__<hash>]``.
    tail = name[len(TOOL_NAME_PREFIX):]
    return TOOL_NAME_SEP in tail
