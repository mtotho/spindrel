"""Startup-owned environment file and first-boot secret helpers."""
from __future__ import annotations

import logging
import os
import re
import secrets
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

_DOTENV_MODE = 0o600


def _dotenv_path(path: str | os.PathLike[str] | None = None) -> Path:
    return Path(path) if path is not None else Path.cwd() / ".env"


def _secure_dotenv(path: Path) -> None:
    try:
        path.chmod(_DOTENV_MODE)
    except OSError:
        logger.debug("Could not chmod %s to 0600", path, exc_info=True)


def upsert_dotenv_value(
    path: str | os.PathLike[str] | None,
    key: str,
    value: str,
) -> bool:
    """Create or update ``key=value`` in a dotenv file.

    Existing commented assignments such as ``# JWT_SECRET=...`` are treated as
    the key's current slot and replaced. Returns ``True`` when file content
    changed.
    """
    dotenv = _dotenv_path(path)
    dotenv.parent.mkdir(parents=True, exist_ok=True)
    line = f"{key}={value}"
    pattern = re.compile(rf"^#?\s*{re.escape(key)}=.*$", re.MULTILINE)

    if dotenv.exists():
        original = dotenv.read_text()
        if pattern.search(original):
            updated = pattern.sub(line, original, count=1)
        else:
            sep = "" if original.endswith("\n") or not original else "\n"
            updated = f"{original}{sep}{line}\n"
    else:
        original = None
        updated = f"{line}\n"

    if original == updated:
        _secure_dotenv(dotenv)
        return False

    dotenv.write_text(updated)
    _secure_dotenv(dotenv)
    return True


def sync_home_host_dir_from_spindrel_home(
    path: str | os.PathLike[str] | None = None,
) -> bool:
    """Persist ``SPINDREL_HOME`` as ``HOME_HOST_DIR`` for the next compose boot."""
    if not settings.SPINDREL_HOME or os.environ.get("HOME_HOST_DIR"):
        return False
    try:
        changed = upsert_dotenv_value(path, "HOME_HOST_DIR", settings.SPINDREL_HOME)
    except OSError:
        logger.warning("Could not sync SPINDREL_HOME to .env; set HOME_HOST_DIR manually")
        return False
    logger.info(
        "Synced SPINDREL_HOME=%s to .env as HOME_HOST_DIR (takes effect on next restart)",
        settings.SPINDREL_HOME,
    )
    return changed


async def ensure_encryption_key(
    path: str | os.PathLike[str] | None = None,
) -> str | None:
    """Generate and persist ``ENCRYPTION_KEY`` when first boot has no secrets."""
    from app.services.encryption import (
        generate_key,
        is_encryption_enabled,
        reset as reset_encryption,
    )

    if is_encryption_enabled():
        return settings.ENCRYPTION_KEY or None

    from app.services.providers import has_encrypted_secrets

    if await has_encrypted_secrets():
        raise RuntimeError(
            "ENCRYPTION_KEY is not set but the database contains encrypted secrets (enc: prefix). "
            "These values cannot be decrypted without the original key. "
            "Set ENCRYPTION_KEY in .env to the key used to encrypt them."
        )

    new_key = generate_key()
    settings.ENCRYPTION_KEY = new_key
    reset_encryption()
    try:
        upsert_dotenv_value(path, "ENCRYPTION_KEY", new_key)
        logger.info("Auto-generated ENCRYPTION_KEY and saved to .env; back this up")
    except OSError:
        logger.warning(
            "Auto-generated ENCRYPTION_KEY but could not write to .env. "
            "Add the key from the running config to your environment to persist it."
        )
    return new_key


def ensure_jwt_secret(
    path: str | os.PathLike[str] | None = None,
) -> str:
    """Ensure JWT signing uses a persistent secret after startup."""
    from app.services.auth import configure_jwt_secret

    if settings.JWT_SECRET:
        return configure_jwt_secret(settings.JWT_SECRET)

    new_secret = secrets.token_hex(32)
    settings.JWT_SECRET = new_secret
    configure_jwt_secret(new_secret)
    try:
        upsert_dotenv_value(path, "JWT_SECRET", new_secret)
        logger.info("Auto-generated JWT_SECRET and saved to .env")
    except OSError:
        logger.warning(
            "Auto-generated JWT_SECRET but could not write to .env. "
            "Set JWT_SECRET in your environment to preserve login sessions across restarts."
        )
    return new_secret
