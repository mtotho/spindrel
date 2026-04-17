"""Seed integration lifecycle status.

Converts the old boolean ``_disabled`` setting into the new two-state
``_status`` lifecycle row (``available`` | ``enabled``). "Needs setup" is not
a lifecycle state — it's a derived readiness flag surfaced at runtime from
``is_configured``.

Assignment rules (evaluated per integration_id that has any
``integration_settings`` row):

1. Had ``_disabled = "true"`` → ``available`` (plus delete the ``_disabled`` row).
2. Else → ``enabled`` (the integration was previously active or in-progress;
   if required settings are missing the UI will show a Needs Setup badge and
   the auto-start loop simply won't spin up the process).

Integrations without any settings rows are left alone — ``available`` is the
default when ``_status`` is missing.

Revision ID: 201
Revises: 200
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "201"
down_revision = "200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    rows = bind.execute(sa.text(
        "SELECT integration_id, key, value FROM integration_settings"
    )).fetchall()
    by_integration: dict[str, dict[str, str]] = {}
    for iid, key, value in rows:
        by_integration.setdefault(iid, {})[key] = value or ""

    for iid, settings in by_integration.items():
        if "_status" in settings and settings["_status"] in ("available", "enabled"):
            # Idempotent: already migrated.
            continue

        was_disabled = (settings.get("_disabled", "").lower() in ("true", "1", "yes"))
        status = "available" if was_disabled else "enabled"

        bind.execute(
            sa.text(
                "INSERT INTO integration_settings (integration_id, key, value, is_secret, updated_at) "
                "VALUES (:iid, :key, :val, false, NOW()) "
                "ON CONFLICT (integration_id, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
            ),
            {"iid": iid, "key": "_status", "val": status},
        )

    # Drop the now-obsolete `_disabled` rows.
    bind.execute(sa.text("DELETE FROM integration_settings WHERE key = '_disabled'"))
    # Also coerce any transitional `needs_setup` rows (from earlier alpha of
    # this migration) to `enabled` — the new model treats them as adopted.
    bind.execute(sa.text(
        "UPDATE integration_settings SET value = 'enabled' "
        "WHERE key = '_status' AND value = 'needs_setup'"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    # Best-effort: `available` with any non-empty settings → `_disabled=true`.
    bind.execute(sa.text(
        """
        INSERT INTO integration_settings (integration_id, key, value, is_secret, updated_at)
        SELECT s.integration_id, '_disabled', 'true', false, NOW()
        FROM integration_settings s
        WHERE s.key = '_status' AND s.value = 'available'
          AND EXISTS (
            SELECT 1 FROM integration_settings o
            WHERE o.integration_id = s.integration_id
              AND o.key NOT IN ('_status', '_disabled')
              AND COALESCE(o.value, '') <> ''
          )
        ON CONFLICT (integration_id, key) DO UPDATE SET value = 'true', updated_at = NOW()
        """
    ))
    bind.execute(sa.text("DELETE FROM integration_settings WHERE key = '_status'"))
