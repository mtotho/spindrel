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
class WidgetManifest:
    name: str
    version: str
    description: str
    permissions: Permissions
    cron: list[CronEntry]
    events: list[EventEntry]
    db: DbConfig | None
    source_path: Path | None = None
    # Third-party origin allowances the bundle needs at render time
    # (Google Maps JS, Mapbox tiles, etc.). Same shape + validation as the
    # envelope's ``extra_csp``: ``{directive: [https://origin, ...]}``. When
    # present, the catalog pin flow forwards this onto the envelope so
    # cross-channel / cross-dashboard re-pins keep working without
    # re-invoking the original ``emit_html_widget`` call.
    extra_csp: dict[str, list[str]] | None = None


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

    # Verify contiguous sequence starting from 1 (if any migrations exist).
    if migrations:
        for i, m in enumerate(migrations):
            expected_from = i + 1
            if m.from_version != expected_from:
                raise ManifestError(
                    f"db.migrations must be ordered from 1 to {sv}; "
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

    return WidgetManifest(
        name=name.strip(),
        version=version,
        description=description,
        permissions=permissions,
        cron=cron,
        events=events,
        db=db,
        source_path=path,
        extra_csp=extra_csp,
    )
