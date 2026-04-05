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
    metadata     TEXT,
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

CREATE TABLE IF NOT EXISTS cursors (
    key          TEXT PRIMARY KEY,
    value        TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
"""


class IngestionStore:
    """Thin wrapper around a per-integration SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Add columns introduced after initial schema (idempotent)."""
        try:
            self._conn.execute("ALTER TABLE quarantine ADD COLUMN metadata TEXT")
            self._conn.commit()
        except Exception:
            pass  # Column already exists

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
        metadata: dict | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO quarantine (source, source_id, raw_content, risk_level, flags, reason, metadata, quarantined_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (source, source_id, raw_content, risk_level, json.dumps(flags or []), reason, json.dumps(metadata) if metadata else None, now),
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

    def unquarantine(self, quarantine_ids: list[int]) -> int:
        """Release specific quarantined items by ID. Removes from quarantine + processed_ids, adds audit entry. Returns count released."""
        if not quarantine_ids:
            return 0
        placeholders = ",".join("?" for _ in quarantine_ids)
        # Fetch rows to remove from processed_ids
        rows = self._conn.execute(
            f"SELECT id, source, source_id FROM quarantine WHERE id IN ({placeholders})",
            quarantine_ids,
        ).fetchall()
        if not rows:
            return 0
        # Delete from quarantine
        self._conn.execute(
            f"DELETE FROM quarantine WHERE id IN ({placeholders})",
            quarantine_ids,
        )
        # Delete from processed_ids so the message can be re-ingested
        for r in rows:
            self._conn.execute(
                "DELETE FROM processed_ids WHERE source = ? AND source_id = ?",
                (r["source"], r["source_id"]),
            )
            self.audit(r["source"], r["source_id"], "unquarantined")
        self._conn.commit()
        return len(rows)

    def unquarantine_by_reason(self, reason_pattern: str, source: str | None = None) -> int:
        """Bulk release quarantined items matching a reason LIKE pattern. Returns count released."""
        if source:
            rows = self._conn.execute(
                "SELECT id, source, source_id FROM quarantine WHERE reason LIKE ? AND source = ?",
                (reason_pattern, source),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, source, source_id FROM quarantine WHERE reason LIKE ?",
                (reason_pattern,),
            ).fetchall()
        if not rows:
            return 0
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" for _ in ids)
        self._conn.execute(
            f"DELETE FROM quarantine WHERE id IN ({placeholders})", ids
        )
        for r in rows:
            self._conn.execute(
                "DELETE FROM processed_ids WHERE source = ? AND source_id = ?",
                (r["source"], r["source_id"]),
            )
            self.audit(r["source"], r["source_id"], "unquarantined")
        self._conn.commit()
        return len(rows)

    # -- audit log ----------------------------------------------------------

    def audit(self, source: str, source_id: str, action: str, risk_level: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO audit_log (source, source_id, action, risk_level, ts) VALUES (?, ?, ?, ?, ?)",
            (source, source_id, action, risk_level, now),
        )
        self._conn.commit()

    # -- cursors -----------------------------------------------------------

    def get_cursor(self, key: str) -> str | None:
        """Get a cursor value by key. Returns None if not set."""
        row = self._conn.execute(
            "SELECT value FROM cursors WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def set_cursor(self, key: str, value: str) -> None:
        """Set a cursor value (upsert)."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO cursors (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, now),
        )
        self._conn.commit()

    # -- query helpers -----------------------------------------------------

    def get_feed_stats(self, source: str | None = None) -> dict:
        """Return aggregate stats, optionally filtered by source.

        Returns total processed, total quarantined, 24h counts, last cursor.
        """
        cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        where = "WHERE source = ?" if source else ""
        params: tuple = (source,) if source else ()

        total_processed = self._conn.execute(
            f"SELECT COUNT(*) AS cnt FROM audit_log {where}", params
        ).fetchone()["cnt"]

        total_quarantined = self._conn.execute(
            f"SELECT COUNT(*) AS cnt FROM quarantine {where}", params
        ).fetchone()["cnt"]

        where_24h = f"WHERE ts >= ?{' AND source = ?' if source else ''}"
        params_24h: tuple = (cutoff_24h, source) if source else (cutoff_24h,)
        processed_24h = self._conn.execute(
            f"SELECT COUNT(*) AS cnt FROM audit_log {where_24h}", params_24h
        ).fetchone()["cnt"]

        quarantined_24h = self._conn.execute(
            f"SELECT COUNT(*) AS cnt FROM quarantine WHERE quarantined_at >= ?{' AND source = ?' if source else ''}",
            params_24h,
        ).fetchone()["cnt"]

        # Last cursor(s) for this source — handles composite keys like "gmail:INBOX"
        if source:
            rows = self._conn.execute(
                "SELECT key, value, updated_at FROM cursors WHERE key = ? OR key LIKE ?",
                (source, f"{source}:%"),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT key, value, updated_at FROM cursors"
            ).fetchall()
        last_cursor = [
            {"key": r["key"], "value": r["value"], "updated_at": r["updated_at"]}
            for r in rows
        ]

        return {
            "total_processed": total_processed,
            "total_quarantined": total_quarantined,
            "processed_24h": processed_24h,
            "quarantined_24h": quarantined_24h,
            "last_cursor": last_cursor,
        }

    def get_recent_items(self, source: str | None = None, limit: int = 20) -> list[dict]:
        """Return recent passed items from audit_log."""
        if source:
            rows = self._conn.execute(
                "SELECT source, source_id, action, risk_level, ts FROM audit_log "
                "WHERE action = 'passed' AND source = ? ORDER BY ts DESC LIMIT ?",
                (source, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT source, source_id, action, risk_level, ts FROM audit_log "
                "WHERE action = 'passed' ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_quarantine_items(self, source: str | None = None, limit: int = 20) -> list[dict]:
        """Return quarantined items with id, risk/flags/reason/metadata (no raw_content)."""
        if source:
            rows = self._conn.execute(
                "SELECT id, source, source_id, risk_level, flags, reason, metadata, quarantined_at "
                "FROM quarantine WHERE source = ? ORDER BY quarantined_at DESC LIMIT ?",
                (source, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, source, source_id, risk_level, flags, reason, metadata, quarantined_at "
                "FROM quarantine ORDER BY quarantined_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["flags"] = json.loads(d["flags"]) if d["flags"] else []
            d["metadata"] = json.loads(d["metadata"]) if d["metadata"] else None
            result.append(d)
        return result

    def get_quarantine_item(self, item_id: int) -> dict | None:
        """Return a single quarantine item with full details including raw_content."""
        row = self._conn.execute(
            "SELECT id, source, source_id, raw_content, risk_level, flags, reason, metadata, quarantined_at "
            "FROM quarantine WHERE id = ?",
            (item_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["flags"] = json.loads(d["flags"]) if d["flags"] else []
        d["metadata"] = json.loads(d["metadata"]) if d["metadata"] else None
        return d

    def count_by_reason_prefix(self, source: str | None, prefix: str) -> int:
        """Count quarantine items where reason starts with prefix."""
        pattern = f"{prefix}%"
        if source:
            row = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM quarantine WHERE reason LIKE ? AND source = ?",
                (pattern, source),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM quarantine WHERE reason LIKE ?",
                (pattern,),
            ).fetchone()
        return row["cnt"]

    def list_sources(self) -> list[str]:
        """Return distinct sources from audit_log."""
        rows = self._conn.execute(
            "SELECT DISTINCT source FROM audit_log ORDER BY source"
        ).fetchall()
        return [r["source"] for r in rows]

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self._conn.close()
