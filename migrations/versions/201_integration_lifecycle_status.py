"""Seed integration lifecycle status.

Converts the old boolean ``_disabled`` integration setting into the new
``_status`` lifecycle setting (``available`` | ``needs_setup`` | ``enabled``).

Assignment rules (evaluated per integration_id that has any ``integration_settings`` row):

1. Had ``_disabled = "true"`` → ``available`` (plus delete the ``_disabled`` row).
2. Else, all required settings (from ``integration_manifests.manifest.settings``) present → ``enabled``.
3. Else, at least one required setting present (partial setup) → ``needs_setup``.
4. Else → ``available``.

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


def _required_keys_by_integration(bind) -> dict[str, list[str]]:
    """Read `integration_manifests.manifest -> settings[*].required` for each id."""
    rows = bind.execute(sa.text("SELECT id, manifest FROM integration_manifests"))
    out: dict[str, list[str]] = {}
    for row in rows:
        iid, manifest = row[0], row[1]
        if not manifest:
            out[iid] = []
            continue
        settings_spec = manifest.get("settings", []) if isinstance(manifest, dict) else []
        required: list[str] = []
        for s in settings_spec:
            if s.get("required") and s.get("key"):
                required.append(s["key"])
        out[iid] = required
    return out


def upgrade() -> None:
    bind = op.get_bind()

    # Collect all (integration_id, key, value) rows once.
    rows = bind.execute(sa.text(
        "SELECT integration_id, key, value FROM integration_settings"
    )).fetchall()
    by_integration: dict[str, dict[str, str]] = {}
    for iid, key, value in rows:
        by_integration.setdefault(iid, {})[key] = value or ""

    required_keys = _required_keys_by_integration(bind)

    for iid, settings in by_integration.items():
        # Skip if already has _status (idempotent).
        if "_status" in settings:
            continue

        was_disabled = (settings.get("_disabled", "").lower() in ("true", "1", "yes"))
        if was_disabled:
            status = "available"
        else:
            req = required_keys.get(iid, [])
            if not req:
                # No required keys. If the integration was never disabled we
                # call it enabled — historically it was active.
                status = "enabled"
            else:
                set_count = sum(1 for k in req if settings.get(k))
                if set_count == len(req):
                    status = "enabled"
                elif set_count > 0:
                    status = "needs_setup"
                else:
                    status = "available"

        bind.execute(
            sa.text(
                "INSERT INTO integration_settings (integration_id, key, value, is_secret, updated_at) "
                "VALUES (:iid, :key, :val, false, NOW()) "
                "ON CONFLICT (integration_id, key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()"
            ),
            {"iid": iid, "key": "_status", "val": status},
        )

    # Drop the now-obsolete `_disabled` rows.
    bind.execute(sa.text(
        "DELETE FROM integration_settings WHERE key = '_disabled'"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    # Best-effort: anything currently `available` that has any non-empty
    # settings row becomes `_disabled=true`; the rest lose the status marker.
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
