"""Server-side SQLite per widget bundle — Phase B.1 of the Widget SDK track.

Each pinned widget bundle can have one ``data.sqlite`` file in its bundle
directory.  For built-in bundles (under ``app/tools/local/widgets/``) the
DB is redirected to ``{workspace_base}/widget_db/builtin/<slug>/data.sqlite``
so the server source tree stays read-only in Docker.

Public surface
--------------
resolve_db_path(pin) → Path
acquire_db(path, db_config?) → async context manager → sqlite3.Connection
run_migrations(conn, db_config) → None
has_content(path) → bool
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

if TYPE_CHECKING:
    from app.db.models import WidgetDashboardPin
    from app.services.widget_manifest import DbConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-path async locks — prevents concurrent writes to the same DB file.
# ---------------------------------------------------------------------------

_DB_LOCKS: dict[Path, asyncio.Lock] = {}
_DB_LOCKS_MUTEX = asyncio.Lock()


async def _get_lock(path: Path) -> asyncio.Lock:
    async with _DB_LOCKS_MUTEX:
        if path not in _DB_LOCKS:
            _DB_LOCKS[path] = asyncio.Lock()
        return _DB_LOCKS[path]


# ---------------------------------------------------------------------------
# Built-in bundle redirect
# ---------------------------------------------------------------------------

# Built-in widget bundles live in the app source tree (read-only in Docker).
_BUILTIN_WIDGET_DIR = (
    Path(__file__).resolve().parents[2] / "tools" / "local" / "widgets"
).resolve()


def _builtin_db_root() -> Path:
    from app.services.paths import local_workspace_base
    return Path(local_workspace_base()) / "widget_db" / "builtin"


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def resolve_db_path(pin: "WidgetDashboardPin") -> Path:
    """Derive the ``data.sqlite`` path for the bundle this pin references.

    Uses ``pin.envelope.source_path`` (workspace-relative) + ``source_channel_id``
    + ``source_bot_id`` to compute the channel workspace root and then the
    bundle directory.

    Raises ``ValueError`` for:
    - Inline widgets (no ``source_path`` in envelope)
    - Missing channel/bot identity
    - Path traversal outside the channel workspace
    """
    envelope: dict = pin.envelope or {}
    source_path: str | None = envelope.get("source_path")
    if not source_path:
        raise ValueError(
            "inline widgets do not have a server-side SQLite DB; "
            "only path-mode widgets (emit_html_widget path=...) support spindrel.db"
        )

    channel_id: str | None = (
        str(pin.source_channel_id) if pin.source_channel_id else envelope.get("source_channel_id")
    )
    bot_id: str | None = pin.source_bot_id or envelope.get("source_bot_id")

    if not channel_id:
        raise ValueError("pin missing source_channel_id — cannot resolve DB path")
    if not bot_id:
        raise ValueError("pin missing source_bot_id — cannot resolve DB path")

    from app.agent.bots import get_bot
    from app.services.channel_workspace import get_channel_workspace_root

    bot = get_bot(bot_id)
    if bot is None:
        raise ValueError(f"bot {bot_id!r} not found — cannot resolve DB path")

    ws_root = Path(get_channel_workspace_root(channel_id, bot)).resolve()
    # Resolve the bundle directory (parent of the index.html).
    bundle_dir = (ws_root / source_path).resolve().parent

    # Path traversal guard: bundle_dir must stay inside the channel workspace.
    try:
        bundle_dir.relative_to(ws_root)
    except ValueError:
        raise ValueError(
            f"source_path {source_path!r} resolves outside the channel workspace "
            f"(workspace_root={ws_root})"
        )

    # Redirect built-in bundles to the writable widget_db area so the Docker
    # image's read-only source tree isn't written to.
    try:
        bundle_dir.relative_to(_BUILTIN_WIDGET_DIR)
        slug = bundle_dir.name
        redirect_dir = _builtin_db_root() / slug
        redirect_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("Built-in widget DB redirect: %s → %s", bundle_dir, redirect_dir)
        return redirect_dir / "data.sqlite"
    except ValueError:
        pass

    return bundle_dir / "data.sqlite"


# ---------------------------------------------------------------------------
# Migration runner
# ---------------------------------------------------------------------------


def run_migrations(conn: sqlite3.Connection, db_config: "DbConfig") -> None:
    """Apply pending schema migrations from a widget manifest's ``db`` block.

    Uses SQLite ``PRAGMA user_version`` as the authoritative schema-version
    counter.  Each migration step runs via ``executescript`` (which
    auto-commits) then bumps ``user_version``.

    Raises ``ValueError`` on:
    - Downgrade attempt (on-disk version > manifest version)
    - Migration gap (missing intermediate step)
    - SQL execution error
    """
    current: int = conn.execute("PRAGMA user_version").fetchone()[0]
    target: int = db_config.schema_version

    if current > target:
        raise ValueError(
            f"DB user_version ({current}) is newer than manifest "
            f"schema_version ({target}) — downgrade refused"
        )

    for step in db_config.migrations:
        if step.from_version < current:
            continue  # already applied
        if step.from_version != current:
            raise ValueError(
                f"Migration gap: current version is {current} but the "
                f"next declared step starts at from={step.from_version}"
            )
        try:
            conn.executescript(step.sql)
        except Exception as exc:
            raise ValueError(
                f"Migration {step.from_version}→{step.to_version} failed: {exc}"
            ) from exc
        # executescript auto-commits, so we can set user_version directly.
        conn.execute(f"PRAGMA user_version = {step.to_version}")
        current = step.to_version

    # If no migration steps were declared but user_version < target, that's
    # a manifest error (would have been caught at parse time, but double-check).
    if current != target:
        raise ValueError(
            f"Migrations incomplete: ended at version {current}, "
            f"expected {target}"
        )


# ---------------------------------------------------------------------------
# DB context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def acquire_db(
    path: Path,
    db_config: "DbConfig | None" = None,
) -> AsyncGenerator[sqlite3.Connection, None]:
    """Open the widget SQLite DB, run pending migrations, yield the connection.

    Holds the per-path asyncio lock for the duration so concurrent widget
    dispatches targeting the same DB are serialised.  The actual I/O runs in
    a thread executor to keep the event loop free.

    WAL mode is set on every open — safe to call repeatedly.
    """
    lock = await _get_lock(path)
    async with lock:

        def _open() -> sqlite3.Connection:
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            if db_config is not None:
                run_migrations(conn, db_config)
            return conn

        conn: sqlite3.Connection = await asyncio.to_thread(_open)
        try:
            yield conn
        finally:
            await asyncio.to_thread(conn.close)


# ---------------------------------------------------------------------------
# Content probe
# ---------------------------------------------------------------------------


def has_content(path: Path) -> bool:
    """Return True if the DB file exists and any user table has ≥1 row.

    Used by the unpin-warning path to decide whether to surface a "your data
    will be lost" confirmation before deleting a pin whose bundle has a DB.
    """
    if not path.exists():
        return False
    try:
        conn = sqlite3.connect(str(path))
        try:
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            ]
            for table in tables:
                if conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0] > 0:
                    return True
            return False
        finally:
            conn.close()
    except Exception:
        logger.debug("has_content(%s) failed — treating as empty", path, exc_info=True)
        return False
