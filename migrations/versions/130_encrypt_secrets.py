"""Encrypt existing provider API keys and integration secrets.

Reads ENCRYPTION_KEY from the environment. If not set, this migration is a
no-op — values remain as plaintext and can be encrypted later by setting the
key and re-running (or the next create/update will encrypt automatically).

Revision ID: 130
Revises: 129
"""

import os

from alembic import op
import sqlalchemy as sa

revision = "130"
down_revision = "129"


def _get_fernet():
    """Build a Fernet instance from ENCRYPTION_KEY env var, or None."""
    key = os.environ.get("ENCRYPTION_KEY", "")
    if not key:
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode())
    except Exception:
        print("WARNING: Invalid ENCRYPTION_KEY — skipping encryption migration")
        return None


ENCRYPTED_PREFIX = "enc:"


def upgrade() -> None:
    fernet = _get_fernet()
    if fernet is None:
        print("ENCRYPTION_KEY not set — skipping secret encryption (values remain plaintext)")
        return

    conn = op.get_bind()

    # Encrypt provider_configs.api_key
    rows = conn.execute(
        sa.text("SELECT id, api_key FROM provider_configs WHERE api_key IS NOT NULL AND api_key != ''")
    ).fetchall()
    for row in rows:
        if row.api_key.startswith(ENCRYPTED_PREFIX):
            continue  # already encrypted
        encrypted = ENCRYPTED_PREFIX + fernet.encrypt(row.api_key.encode("utf-8")).decode("utf-8")
        conn.execute(
            sa.text("UPDATE provider_configs SET api_key = :val WHERE id = :id"),
            {"val": encrypted, "id": row.id},
        )
    if rows:
        print(f"Encrypted {len(rows)} provider API key(s)")

    # Encrypt provider_configs.config->'management_key'
    mgmt_rows = conn.execute(
        sa.text(
            "SELECT id, config FROM provider_configs "
            "WHERE config IS NOT NULL AND config::text LIKE '%management_key%'"
        )
    ).fetchall()
    for row in mgmt_rows:
        import json
        config = row.config if isinstance(row.config, dict) else json.loads(row.config)
        mgmt_key = config.get("management_key", "")
        if not mgmt_key or mgmt_key.startswith(ENCRYPTED_PREFIX):
            continue
        config["management_key"] = ENCRYPTED_PREFIX + fernet.encrypt(mgmt_key.encode("utf-8")).decode("utf-8")
        conn.execute(
            sa.text("UPDATE provider_configs SET config = :val WHERE id = :id"),
            {"val": json.dumps(config), "id": row.id},
        )
    if mgmt_rows:
        print(f"Checked {len(mgmt_rows)} provider config(s) for management_key encryption")

    # Encrypt integration_settings.value where is_secret=True
    secret_rows = conn.execute(
        sa.text(
            "SELECT integration_id, key, value FROM integration_settings "
            "WHERE is_secret = true AND value IS NOT NULL AND value != ''"
        )
    ).fetchall()
    for row in secret_rows:
        if row.value.startswith(ENCRYPTED_PREFIX):
            continue
        encrypted = ENCRYPTED_PREFIX + fernet.encrypt(row.value.encode("utf-8")).decode("utf-8")
        conn.execute(
            sa.text(
                "UPDATE integration_settings SET value = :val "
                "WHERE integration_id = :iid AND key = :key"
            ),
            {"val": encrypted, "iid": row.integration_id, "key": row.key},
        )
    if secret_rows:
        print(f"Encrypted {len(secret_rows)} integration secret(s)")


def downgrade() -> None:
    fernet = _get_fernet()
    if fernet is None:
        print("ENCRYPTION_KEY not set — cannot decrypt (values may remain encrypted)")
        return

    conn = op.get_bind()

    # Decrypt provider_configs.api_key
    rows = conn.execute(
        sa.text("SELECT id, api_key FROM provider_configs WHERE api_key IS NOT NULL AND api_key LIKE 'enc:%'")
    ).fetchall()
    for row in rows:
        ciphertext = row.api_key[len(ENCRYPTED_PREFIX):]
        plaintext = fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        conn.execute(
            sa.text("UPDATE provider_configs SET api_key = :val WHERE id = :id"),
            {"val": plaintext, "id": row.id},
        )

    # Decrypt provider_configs.config->'management_key'
    mgmt_rows = conn.execute(
        sa.text(
            "SELECT id, config FROM provider_configs "
            "WHERE config IS NOT NULL AND config::text LIKE '%management_key%'"
        )
    ).fetchall()
    for row in mgmt_rows:
        import json
        config = row.config if isinstance(row.config, dict) else json.loads(row.config)
        mgmt_key = config.get("management_key", "")
        if not mgmt_key or not mgmt_key.startswith(ENCRYPTED_PREFIX):
            continue
        ciphertext = mgmt_key[len(ENCRYPTED_PREFIX):]
        config["management_key"] = fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        conn.execute(
            sa.text("UPDATE provider_configs SET config = :val WHERE id = :id"),
            {"val": json.dumps(config), "id": row.id},
        )

    # Decrypt integration_settings.value where is_secret=True
    secret_rows = conn.execute(
        sa.text(
            "SELECT integration_id, key, value FROM integration_settings "
            "WHERE is_secret = true AND value IS NOT NULL AND value LIKE 'enc:%'"
        )
    ).fetchall()
    for row in secret_rows:
        ciphertext = row.value[len(ENCRYPTED_PREFIX):]
        plaintext = fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        conn.execute(
            sa.text(
                "UPDATE integration_settings SET value = :val "
                "WHERE integration_id = :iid AND key = :key"
            ),
            {"val": plaintext, "iid": row.integration_id, "key": row.key},
        )
