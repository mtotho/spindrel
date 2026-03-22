"""SQLite helpers — schema init, quarantine, audit log, idempotency."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_ids (
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    PRIMARY KEY (source, source_id)
);

CREATE TABLE IF NOT EXISTS quarantine (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    raw_content  TEXT NOT NULL,
    risk_level   TEXT NOT NULL,
    flags        TEXT,
    reason       TEXT,
    quarantined_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    action       TEXT NOT NULL,
    risk_level   TEXT,
    ts           TEXT NOT NULL
);
"""


class IngestionStore:
    """Thin wrapper around a per-integration SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)

    # -- idempotency --------------------------------------------------------

    def already_processed(self, source: str, source_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM processed_ids WHERE source = ? AND source_id = ?",
            (source, source_id),
        ).fetchone()
        return row is not None

    def mark_processed(self, source: str, source_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT OR IGNORE INTO processed_ids (source, source_id, processed_at) VALUES (?, ?, ?)",
            (source, source_id, now),
        )
        self._conn.commit()

    # -- quarantine ---------------------------------------------------------

    def quarantine(
        self,
        source: str,
        source_id: str,
        raw_content: str,
        risk_level: str,
        flags: list[str] | None = None,
        reason: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO quarantine (source, source_id, raw_content, risk_level, flags, reason, quarantined_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (source, source_id, raw_content, risk_level, json.dumps(flags or []), reason, now),
        )
        self._conn.commit()

    def purge_quarantine(self, retention_days: int = 90) -> int:
        """Delete quarantined items older than retention_days. Returns count deleted."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        cur = self._conn.execute(
            "DELETE FROM quarantine WHERE quarantined_at < ?", (cutoff,)
        )
        self._conn.commit()
        return cur.rowcount

    # -- audit log ----------------------------------------------------------

    def audit(self, source: str, source_id: str, action: str, risk_level: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO audit_log (source, source_id, action, risk_level, ts) VALUES (?, ?, ?, ?, ?)",
            (source, source_id, action, risk_level, now),
        )
        self._conn.commit()

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self._conn.close()
