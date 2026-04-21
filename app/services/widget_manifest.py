"""Widget bundle manifest parser and validator.

Reads ``widget.yaml`` from a bundle directory and returns a validated
``WidgetManifest`` dataclass.  Raises ``ManifestError`` on any
structural or semantic validation failure.

Used by ``html_widget_scanner`` (catalog enrichment) and later by
``widget_py`` (handler registration) and ``widget_cron`` (subscription
lifecycle).  All validation is synchronous and import-free from the
router layer — no DB or async calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ManifestError(ValueError):
    """Raised when a widget.yaml fails structural or semantic validation."""


# ---------------------------------------------------------------------------
# Nested dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MigrationEntry:
    from_version: int
    to_version: int
    sql: str


@dataclass
class DbConfig:
    schema_version: int
    migrations: list[MigrationEntry] = field(default_factory=list)
    shared: str | None = None


@dataclass
class CronEntry:
    name: str
    schedule: str
    handler: str


@dataclass
class EventEntry:
    kind: str
    handler: str


@dataclass
class Permissions:
    tools: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)


@dataclass
class HandlerSpec:
    """Declarative description of a widget ``@on_action`` handler.

    When ``bot_callable`` is true, the dynamic widget-handler tool source
    (``app/services/widget_handler_tools.py``) exposes this handler to bots
    as a tool named ``widget__<slug>__<name>``. Bots get schema-correct calls
    via the standard tool-policy pipeline; the handler still runs under the
    pin's ``source_bot_id`` (same identity as iframe-dispatched calls).

    Fields mirror what ``app/tools/registry.register`` stores, so the tool
    registry shape stays uniform across static local tools and dynamic
    widget-handler tools.
    """

    name: str
    description: str = ""
    triggers: list[str] = field(default_factory=list)
    args: dict | None = None  # JSON-Schema fragment (properties/required dict)
    returns: dict | None = None  # JSON-Schema for parsed return value
    bot_callable: bool = False
    safety_tier: str = "mutating"


VALID_HANDLER_SAFETY_TIERS: frozenset[str] = frozenset(
    {"readonly", "mutating", "exec_capable"}
)


@dataclass
class LayoutHints:
    """Authoring-time hints for where a widget belongs in the dashboard editor.

    Advisory only — the dashboard editor reads ``preferred_zone`` to suggest
    placement and ``min_cells`` / ``max_cells`` to clamp resize so a 180×32
    chip widget can't be stretched into a grid tile (or vice versa). The
    server does not enforce these — pins can always be placed anywhere.
    """

    preferred_zone: str | None = None  # one of VALID_ZONES
    min_cells: dict[str, int] | None = None  # {"w": int, "h": int}
    max_cells: dict[str, int] | None = None


VALID_LAYOUT_ZONES: frozenset[str] = frozenset({"chip", "rail", "dock", "grid"})


@dataclass
class WidgetManifest:
    name: str
    version: str
    description: str
    panel_title: str | None
    show_panel_title: bool | None
    permissions: Permissions
    cron: list[CronEntry]
    events: list[EventEntry]
    db: DbConfig | None
    suite: str | None = None
    package: str | None = None
    source_path: Path | None = None
    # Third-party origin allowances the bundle needs at render time
    # (Google Maps JS, Mapbox tiles, etc.). Same shape + validation as the
    # envelope's ``extra_csp``: ``{directive: [https://origin, ...]}``. When
    # present, the catalog pin flow forwards this onto the envelope so
    # cross-channel / cross-dashboard re-pins keep working without
    # re-invoking the original ``emit_html_widget`` call.
    extra_csp: dict[str, list[str]] | None = None
    # Advisory placement hints for the dashboard editor. Chip-sized widgets
    # set ``preferred_zone: chip`` + ``max_cells: {w: 4, h: 1}``; grid tiles
    # leave this unset. Never enforced server-side.
    layout_hints: LayoutHints | None = None
    # Declarative per-handler metadata. Entries whose ``bot_callable`` is
    # true surface as dynamic tools (``widget__<slug>__<name>``) to bots with
    # the pin in scope. Absent list = no bot-callable handlers on this
    # bundle, which is the safe default.
    handlers: list[HandlerSpec] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_VALID_EVENT_KINDS: frozenset[str] | None = None


def _valid_event_kinds() -> frozenset[str]:
    global _VALID_EVENT_KINDS
    if _VALID_EVENT_KINDS is None:
        from app.domain.channel_events import ChannelEventKind  # lazy, avoids startup cost

        _VALID_EVENT_KINDS = frozenset(e.value for e in ChannelEventKind)
    return _VALID_EVENT_KINDS


_SHARED_SLUG_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
_GROUP_SLUG_RE = __import__("re").compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _validate_db(raw: dict) -> DbConfig:
    if not isinstance(raw, dict):
        raise ManifestError("db must be a mapping")

    shared = raw.get("shared")
    if shared is not None:
        if not isinstance(shared, str) or not _SHARED_SLUG_RE.match(shared):
            raise ManifestError(
                "db.shared must be a slug matching ^[a-z0-9][a-z0-9-]{0,47}$"
            )
        # When opting into a suite-shared DB, the bundle MUST NOT declare
        # schema_version or migrations — the suite manifest owns those. A
        # bundle that both points at a shared DB and tries to migrate it
        # would race other members of the suite.
        if "schema_version" in raw or raw.get("migrations"):
            raise ManifestError(
                "db.shared is mutually exclusive with db.schema_version / db.migrations "
                "— the suite manifest owns the schema"
            )
        return DbConfig(schema_version=0, migrations=[], shared=shared)

    sv = raw.get("schema_version")
    if not isinstance(sv, int) or sv < 1:
        raise ManifestError("db.schema_version must be an integer >= 1")

    raw_migs = raw.get("migrations", [])
    if not isinstance(raw_migs, list):
        raise ManifestError("db.migrations must be a list")

    migrations: list[MigrationEntry] = []
    for i, m in enumerate(raw_migs):
        if not isinstance(m, dict):
            raise ManifestError(f"db.migrations[{i}] must be a mapping")
        frm = m.get("from")
        to = m.get("to")
        sql = m.get("sql", "")
        if not isinstance(frm, int) or not isinstance(to, int):
            raise ManifestError(f"db.migrations[{i}]: 'from' and 'to' must be integers")
        if to != frm + 1:
            raise ManifestError(
                f"db.migrations[{i}]: expected 'to' == 'from' + 1, got from={frm} to={to}"
            )
        if not isinstance(sql, str) or not sql.strip():
            raise ManifestError(f"db.migrations[{i}].sql must be a non-empty string")
        migrations.append(MigrationEntry(from_version=frm, to_version=to, sql=sql))

    # Verify contiguous sequence starting from 0 (matches run_migrations in
    # widget_db.py — a fresh DB has user_version=0, so the first step must
    # begin at from=0). Suite manifests apply the same rule.
    if migrations:
        for i, m in enumerate(migrations):
            expected_from = i
            if m.from_version != expected_from:
                raise ManifestError(
                    f"db.migrations must start from 0 and be contiguous; "
                    f"migration {i} has from={m.from_version}, expected {expected_from}"
                )
        if migrations[-1].to_version != sv:
            raise ManifestError(
                f"db.migrations last step ends at {migrations[-1].to_version} "
                f"but db.schema_version is {sv}"
            )

    return DbConfig(schema_version=sv, migrations=migrations)


def _validate_cron(raw: list) -> list[CronEntry]:
    from app.services.cron_utils import validate_cron  # lazy import

    entries: list[CronEntry] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ManifestError(f"cron[{i}] must be a mapping")
        name = item.get("name")
        schedule = item.get("schedule")
        handler = item.get("handler")
        if not isinstance(name, str) or not name.strip():
            raise ManifestError(f"cron[{i}].name must be a non-empty string")
        if not isinstance(schedule, str):
            raise ManifestError(f"cron[{i}].schedule must be a string")
        try:
            validate_cron(schedule)
        except ValueError as exc:
            raise ManifestError(f"cron[{i}].schedule: {exc}") from exc
        if not isinstance(handler, str) or not handler.strip():
            raise ManifestError(f"cron[{i}].handler must be a non-empty string")
        entries.append(CronEntry(name=name.strip(), schedule=schedule, handler=handler.strip()))
    return entries


def _validate_events(raw: list) -> list[EventEntry]:
    valid_kinds = _valid_event_kinds()
    entries: list[EventEntry] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ManifestError(f"events[{i}] must be a mapping")
        kind = item.get("kind")
        handler = item.get("handler")
        if not isinstance(kind, str) or not kind.strip():
            raise ManifestError(f"events[{i}].kind must be a non-empty string")
        if kind not in valid_kinds:
            raise ManifestError(
                f"events[{i}].kind {kind!r} is not a valid ChannelEventKind; "
                f"valid values: {sorted(valid_kinds)}"
            )
        if not isinstance(handler, str) or not handler.strip():
            raise ManifestError(f"events[{i}].handler must be a non-empty string")
        entries.append(EventEntry(kind=kind, handler=handler.strip()))
    return entries


def _validate_cells(raw: object, field_name: str) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise ManifestError(f"layout_hints.{field_name} must be a mapping")
    out: dict[str, int] = {}
    for key in ("w", "h"):
        if key not in raw:
            continue
        val = raw[key]
        if not isinstance(val, int) or isinstance(val, bool) or val < 1:
            raise ManifestError(
                f"layout_hints.{field_name}.{key} must be an integer >= 1"
            )
        out[key] = val
    extra = set(raw.keys()) - {"w", "h"}
    if extra:
        raise ManifestError(
            f"layout_hints.{field_name}: unknown keys {sorted(extra)!r} "
            f"(allowed: 'w', 'h')"
        )
    return out


def _validate_layout_hints(raw: object) -> LayoutHints:
    if not isinstance(raw, dict):
        raise ManifestError("layout_hints must be a mapping")
    preferred = raw.get("preferred_zone")
    if preferred is not None:
        if not isinstance(preferred, str) or preferred not in VALID_LAYOUT_ZONES:
            raise ManifestError(
                f"layout_hints.preferred_zone must be one of "
                f"{sorted(VALID_LAYOUT_ZONES)}; got {preferred!r}"
            )
    min_cells: dict[str, int] | None = None
    max_cells: dict[str, int] | None = None
    if "min_cells" in raw:
        min_cells = _validate_cells(raw["min_cells"], "min_cells")
    if "max_cells" in raw:
        max_cells = _validate_cells(raw["max_cells"], "max_cells")
    if min_cells and max_cells:
        for k in ("w", "h"):
            if k in min_cells and k in max_cells and min_cells[k] > max_cells[k]:
                raise ManifestError(
                    f"layout_hints.min_cells.{k} ({min_cells[k]}) exceeds "
                    f"max_cells.{k} ({max_cells[k]})"
                )
    return LayoutHints(
        preferred_zone=preferred if isinstance(preferred, str) else None,
        min_cells=min_cells,
        max_cells=max_cells,
    )


_HANDLER_NAME_RE = __import__("re").compile(r"^[a-z][a-z0-9_]{0,63}$")


def _validate_handler_args(raw: object, i: int) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ManifestError(f"handlers[{i}].args must be a mapping (JSON-Schema fragment)")
    for key, spec in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise ManifestError(f"handlers[{i}].args key must be a non-empty string")
        if not isinstance(spec, dict):
            raise ManifestError(
                f"handlers[{i}].args[{key!r}] must be a mapping with 'type'/'description'"
            )
        if "type" in spec and not isinstance(spec["type"], str):
            raise ManifestError(f"handlers[{i}].args[{key!r}].type must be a string")
    return raw


def _validate_handler_returns(raw: object, i: int) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ManifestError(f"handlers[{i}].returns must be a mapping (JSON-Schema)")
    return raw


def _validate_handlers(raw: object) -> list[HandlerSpec]:
    if not isinstance(raw, list):
        raise ManifestError("handlers must be a list")
    seen: set[str] = set()
    out: list[HandlerSpec] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ManifestError(f"handlers[{i}] must be a mapping")
        name = item.get("name")
        if not isinstance(name, str) or not _HANDLER_NAME_RE.match(name):
            raise ManifestError(
                f"handlers[{i}].name must match ^[a-z][a-z0-9_]{{0,63}}$; got {name!r}"
            )
        if name in seen:
            raise ManifestError(f"handlers[{i}].name {name!r} duplicates an earlier entry")
        seen.add(name)

        description = item.get("description", "")
        if not isinstance(description, str):
            raise ManifestError(f"handlers[{i}].description must be a string")

        raw_triggers = item.get("triggers", [])
        if not isinstance(raw_triggers, list):
            raise ManifestError(f"handlers[{i}].triggers must be a list of strings")
        triggers: list[str] = []
        for j, t in enumerate(raw_triggers):
            if not isinstance(t, str) or not t.strip():
                raise ManifestError(
                    f"handlers[{i}].triggers[{j}] must be a non-empty string"
                )
            triggers.append(t.strip())

        args = _validate_handler_args(item.get("args"), i)
        returns = _validate_handler_returns(item.get("returns"), i)

        bot_callable = item.get("bot_callable", False)
        if not isinstance(bot_callable, bool):
            raise ManifestError(f"handlers[{i}].bot_callable must be a boolean")

        safety_tier = item.get("safety_tier", "mutating")
        if safety_tier not in VALID_HANDLER_SAFETY_TIERS:
            raise ManifestError(
                f"handlers[{i}].safety_tier must be one of "
                f"{sorted(VALID_HANDLER_SAFETY_TIERS)}; got {safety_tier!r}"
            )

        # A handler may not be bot-callable without a description — the tool
        # registry + discovery ranker rely on description to surface the tool
        # at retrieval time, and an undescribed tool is worse than no tool.
        if bot_callable and not description.strip():
            raise ManifestError(
                f"handlers[{i}].description is required when bot_callable=true"
            )

        out.append(
            HandlerSpec(
                name=name,
                description=description,
                triggers=triggers,
                args=args,
                returns=returns,
                bot_callable=bot_callable,
                safety_tier=safety_tier,
            )
        )
    return out


def _validate_permissions(raw: dict) -> Permissions:
    if not isinstance(raw, dict):
        raise ManifestError("permissions must be a mapping")

    raw_tools = raw.get("tools", [])
    if not isinstance(raw_tools, list):
        raise ManifestError("permissions.tools must be a list")
    tools: list[str] = []
    for i, t in enumerate(raw_tools):
        if not isinstance(t, str) or not t.strip():
            raise ManifestError(f"permissions.tools[{i}] must be a non-empty string")
        tools.append(t.strip())

    raw_events = raw.get("events", [])
    if not isinstance(raw_events, list):
        raise ManifestError("permissions.events must be a list")
    valid_kinds = _valid_event_kinds()
    events: list[str] = []
    for i, e in enumerate(raw_events):
        if not isinstance(e, str) or not e.strip():
            raise ManifestError(f"permissions.events[{i}] must be a non-empty string")
        if e not in valid_kinds:
            raise ManifestError(
                f"permissions.events[{i}] {e!r} is not a valid ChannelEventKind"
            )
        events.append(e.strip())

    return Permissions(tools=tools, events=events)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_manifest(path: str | Path) -> WidgetManifest:
    """Parse and validate a ``widget.yaml`` file.

    Raises ``ManifestError`` on structural or semantic problems.
    Raises ``OSError`` / ``yaml.YAMLError`` on read/parse failures —
    callers decide whether those are fatal.
    """
    path = Path(path)
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        raise ManifestError("widget.yaml must be a YAML mapping at the top level")

    name = raw.get("name", "")
    if not isinstance(name, str) or not name.strip():
        raise ManifestError("widget.yaml: 'name' must be a non-empty string")

    version = str(raw.get("version", "0.0.0"))
    description = str(raw.get("description", ""))
    raw_panel_title = raw.get("panel_title")
    if raw_panel_title is not None and not isinstance(raw_panel_title, str):
        raise ManifestError("panel_title must be a string when provided")
    panel_title = raw_panel_title.strip() or None if isinstance(raw_panel_title, str) else None
    raw_show_panel_title = raw.get("show_panel_title")
    if raw_show_panel_title is not None and not isinstance(raw_show_panel_title, bool):
        raise ManifestError("show_panel_title must be a boolean when provided")
    raw_suite = raw.get("suite")
    if raw_suite is not None:
        if not isinstance(raw_suite, str) or not _GROUP_SLUG_RE.match(raw_suite.strip()):
            raise ManifestError(
                "suite must be a slug matching ^[a-z0-9][a-z0-9_-]{0,63}$"
            )
        raw_suite = raw_suite.strip()
    raw_package = raw.get("package")
    if raw_package is not None:
        if not isinstance(raw_package, str) or not _GROUP_SLUG_RE.match(raw_package.strip()):
            raise ManifestError(
                "package must be a slug matching ^[a-z0-9][a-z0-9_-]{0,63}$"
            )
        raw_package = raw_package.strip()
    if raw_suite and raw_package:
        raise ManifestError("suite and package are mutually exclusive")

    raw_perms = raw.get("permissions", {})
    permissions = _validate_permissions(raw_perms if isinstance(raw_perms, dict) else {})

    raw_cron = raw.get("cron", [])
    if not isinstance(raw_cron, list):
        raise ManifestError("cron must be a list")
    cron = _validate_cron(raw_cron)

    raw_events = raw.get("events", [])
    if not isinstance(raw_events, list):
        raise ManifestError("events must be a list")
    events = _validate_events(raw_events)

    raw_db = raw.get("db")
    db = _validate_db(raw_db) if raw_db is not None else None

    raw_csp = raw.get("extra_csp")
    extra_csp: dict[str, list[str]] | None = None
    if raw_csp is not None:
        # Reuse the exact tool-dispatch validator so manifest CSP and
        # emit_html_widget CSP stay byte-compatible (same origin-scheme rules,
        # same per-directive caps, same error messages).
        from app.agent.tool_dispatch import _sanitize_extra_csp
        try:
            extra_csp = _sanitize_extra_csp(raw_csp)
        except ValueError as exc:
            raise ManifestError(f"extra_csp: {exc}") from exc

    raw_hints = raw.get("layout_hints")
    layout_hints = _validate_layout_hints(raw_hints) if raw_hints is not None else None

    raw_handlers = raw.get("handlers", [])
    handlers = _validate_handlers(raw_handlers) if raw_handlers else []

    return WidgetManifest(
        name=name.strip(),
        version=version,
        description=description,
        panel_title=panel_title,
        show_panel_title=raw_show_panel_title,
        suite=raw_suite,
        package=raw_package,
        permissions=permissions,
        cron=cron,
        events=events,
        db=db,
        source_path=path,
        extra_csp=extra_csp,
        layout_hints=layout_hints,
        handlers=handlers,
    )
