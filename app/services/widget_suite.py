"""Widget suite manifest parser + discovery — Phase B.6 of the Widget SDK track.

A *suite* is a group of widget bundles that share a server-side SQLite DB.
Members opt in via ``db.shared: <suite_id>`` in their per-bundle widget.yaml;
the matching ``suite.yaml`` at ``app/tools/local/widgets/<suite_id>/``
(or a resolved integration's ``widgets/<suite_id>/``) owns the shared schema.

Public surface
--------------
SuiteManifest                                  — dataclass for parsed suite.yaml
SuiteError                                     — raised on validation failure
parse_suite_manifest(path) -> SuiteManifest    — parse + validate
load_suite(suite_id) -> SuiteManifest | None   — walk known roots, cached by mtime
scan_suites() -> list[SuiteManifest]           — all discoverable suites
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.services.widget_manifest import MigrationEntry

logger = logging.getLogger(__name__)


class SuiteError(ValueError):
    """Raised when a suite.yaml fails structural or semantic validation."""


_SUITE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")


@dataclass
class SuiteManifest:
    suite_id: str
    name: str
    description: str
    members: list[str]
    schema_version: int
    migrations: list[MigrationEntry] = field(default_factory=list)
    source_path: Path | None = None


# ---------------------------------------------------------------------------
# Discovery roots
# ---------------------------------------------------------------------------

_BUILTIN_WIDGETS_DIR = (
    Path(__file__).resolve().parents[1] / "tools" / "local" / "widgets"
).resolve()

def _discovery_roots() -> list[Path]:
    """Return every directory whose subfolders may contain ``<id>/suite.yaml``.

    Suites are identified by the presence of ``suite.yaml`` at the top of
    each subdirectory — they live alongside standalone widgets under
    ``widgets/``, not in a dedicated ``suites/`` folder.
    """
    roots: list[Path] = []
    if _BUILTIN_WIDGETS_DIR.is_dir():
        roots.append(_BUILTIN_WIDGETS_DIR)
    from integrations.discovery import iter_integration_sources

    for source in iter_integration_sources():
        candidate = source.path / "widgets"
        if candidate.is_dir():
            roots.append(candidate.resolve())
    return roots


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _validate_migrations(raw: list, schema_version: int) -> list[MigrationEntry]:
    if not isinstance(raw, list):
        raise SuiteError("db.migrations must be a list")

    migrations: list[MigrationEntry] = []
    for i, m in enumerate(raw):
        if not isinstance(m, dict):
            raise SuiteError(f"db.migrations[{i}] must be a mapping")
        frm = m.get("from")
        to = m.get("to")
        if not isinstance(frm, int) or not isinstance(to, int):
            raise SuiteError(f"db.migrations[{i}]: 'from' and 'to' must be integers")
        if to != frm + 1:
            raise SuiteError(
                f"db.migrations[{i}]: expected 'to' == 'from' + 1, got from={frm} to={to}"
            )
        sql = m.get("sql")
        sql_file = m.get("sql_file")
        if sql is None and sql_file is None:
            raise SuiteError(
                f"db.migrations[{i}] must set either 'sql' or 'sql_file'"
            )
        if sql is not None and sql_file is not None:
            raise SuiteError(
                f"db.migrations[{i}]: 'sql' and 'sql_file' are mutually exclusive"
            )
        # Resolution of sql_file is deferred to load time (we don't have
        # path context here); store the raw value in .sql for now and
        # parse_suite_manifest resolves it.
        payload = sql if sql is not None else f"@file:{sql_file}"
        if not isinstance(payload, str) or not payload.strip():
            raise SuiteError(f"db.migrations[{i}].sql must be a non-empty string")
        migrations.append(MigrationEntry(from_version=frm, to_version=to, sql=payload))

    if migrations:
        for i, m in enumerate(migrations):
            expected_from = i
            if m.from_version != expected_from:
                raise SuiteError(
                    f"db.migrations must start from 0 and be contiguous; "
                    f"migration {i} has from={m.from_version}, expected {expected_from}"
                )
        if migrations[-1].to_version != schema_version:
            raise SuiteError(
                f"db.migrations last step ends at {migrations[-1].to_version} "
                f"but db.schema_version is {schema_version}"
            )

    return migrations


def _resolve_sql_files(migrations: list[MigrationEntry], base_dir: Path) -> None:
    """Replace ``@file:<name>`` placeholders with the file's contents in-place."""
    for m in migrations:
        if m.sql.startswith("@file:"):
            rel = m.sql[len("@file:"):]
            candidate = (base_dir / rel).resolve()
            # Guard: file must live under the suite dir.
            try:
                candidate.relative_to(base_dir.resolve())
            except ValueError:
                raise SuiteError(
                    f"migration sql_file {rel!r} resolves outside the suite directory"
                )
            if not candidate.is_file():
                raise SuiteError(f"migration sql_file not found: {candidate}")
            m.sql = candidate.read_text(encoding="utf-8")


def parse_suite_manifest(path: str | Path) -> SuiteManifest:
    """Parse and validate a ``suite.yaml``.

    ``path`` must be the path to the ``suite.yaml`` file itself, not its
    parent directory. The suite_id is taken from the parent directory name
    and validated against the slug regex.
    """
    path = Path(path)
    if path.name != "suite.yaml":
        raise SuiteError(f"expected a suite.yaml path, got {path.name!r}")
    suite_dir = path.parent

    suite_id = suite_dir.name
    if not _SUITE_ID_RE.match(suite_id):
        raise SuiteError(
            f"suite dir {suite_id!r} is not a valid slug (regex "
            f"^[a-z0-9][a-z0-9-]{{0,47}}$)"
        )

    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        raise SuiteError("suite.yaml must be a YAML mapping at the top level")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise SuiteError("suite.yaml: 'name' must be a non-empty string")

    description = str(raw.get("description", "")).strip()

    raw_members = raw.get("members", [])
    if not isinstance(raw_members, list) or not raw_members:
        raise SuiteError("suite.yaml: 'members' must be a non-empty list of bundle slugs")
    members: list[str] = []
    seen: set[str] = set()
    for i, mem in enumerate(raw_members):
        if not isinstance(mem, str) or not mem.strip():
            raise SuiteError(f"suite.yaml: members[{i}] must be a non-empty string")
        mem = mem.strip()
        if mem in seen:
            raise SuiteError(f"suite.yaml: duplicate member {mem!r}")
        seen.add(mem)
        members.append(mem)

    raw_db = raw.get("db")
    if not isinstance(raw_db, dict):
        raise SuiteError("suite.yaml: 'db' is required and must be a mapping")
    sv = raw_db.get("schema_version")
    if not isinstance(sv, int) or sv < 1:
        raise SuiteError("suite.yaml: db.schema_version must be an integer >= 1")
    migrations = _validate_migrations(raw_db.get("migrations", []), sv)
    _resolve_sql_files(migrations, suite_dir)

    return SuiteManifest(
        suite_id=suite_id,
        name=name.strip(),
        description=description,
        members=members,
        schema_version=sv,
        migrations=migrations,
        source_path=path,
    )


# ---------------------------------------------------------------------------
# Discovery + cache
# ---------------------------------------------------------------------------

# Cache: suite.yaml absolute path -> (mtime, manifest)
_CACHE: dict[str, tuple[float, SuiteManifest]] = {}


def _find_suite_yaml(suite_id: str) -> Path | None:
    for root in _discovery_roots():
        candidate = root / suite_id / "suite.yaml"
        if candidate.is_file():
            return candidate
    return None


def load_suite(suite_id: str) -> SuiteManifest | None:
    """Return the parsed suite manifest for ``suite_id``, or None if missing.

    Cached by (path, mtime) — editing suite.yaml hot-reloads on next call.
    """
    if not _SUITE_ID_RE.match(suite_id):
        return None
    path = _find_suite_yaml(suite_id)
    if path is None:
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    cached = _CACHE.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        manifest = parse_suite_manifest(path)
    except SuiteError:
        logger.exception("parse_suite_manifest failed for %s", path)
        return None
    _CACHE[str(path)] = (mtime, manifest)
    return manifest


def clear_suite_cache() -> None:
    """Test hook — drops every cached suite manifest."""
    _CACHE.clear()


def scan_suites() -> list[SuiteManifest]:
    """Return every discoverable suite manifest, sorted by suite_id."""
    out: list[SuiteManifest] = []
    for root in _discovery_roots():
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            suite_yaml = entry / "suite.yaml"
            if not suite_yaml.is_file():
                continue
            manifest = load_suite(entry.name)
            if manifest is not None:
                out.append(manifest)
    return out
