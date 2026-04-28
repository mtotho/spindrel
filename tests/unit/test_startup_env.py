"""Tests for startup-owned dotenv and first-boot secret helpers."""
from __future__ import annotations

import stat
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import jwt
import pytest

from app.services import startup_env


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_upsert_dotenv_value_creates_file_with_private_mode(tmp_path):
    dotenv = tmp_path / ".env"

    changed = startup_env.upsert_dotenv_value(dotenv, "JWT_SECRET", "secret-1")

    assert changed is True
    assert dotenv.read_text() == "JWT_SECRET=secret-1\n"
    assert _mode(dotenv) == 0o600


def test_upsert_dotenv_value_replaces_commented_assignment(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("API_KEY=abc\n# JWT_SECRET=old\nOTHER=1\n")

    changed = startup_env.upsert_dotenv_value(dotenv, "JWT_SECRET", "new")

    assert changed is True
    assert dotenv.read_text() == "API_KEY=abc\nJWT_SECRET=new\nOTHER=1\n"
    assert _mode(dotenv) == 0o600


def test_upsert_dotenv_value_appends_missing_key(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("API_KEY=abc")

    changed = startup_env.upsert_dotenv_value(dotenv, "JWT_SECRET", "new")

    assert changed is True
    assert dotenv.read_text() == "API_KEY=abc\nJWT_SECRET=new\n"


def test_sync_home_host_dir_uses_spindrel_home(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    monkeypatch.setattr(startup_env.settings, "SPINDREL_HOME", "/srv/spindrel")
    monkeypatch.delenv("HOME_HOST_DIR", raising=False)

    changed = startup_env.sync_home_host_dir_from_spindrel_home(dotenv)

    assert changed is True
    assert dotenv.read_text() == "HOME_HOST_DIR=/srv/spindrel\n"


@pytest.mark.asyncio
async def test_ensure_encryption_key_generates_persists_and_resets(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    monkeypatch.setattr(startup_env.settings, "ENCRYPTION_KEY", "")

    with (
        patch("app.services.encryption.is_encryption_enabled", return_value=False),
        patch("app.services.encryption.generate_key", return_value="generated-key"),
        patch("app.services.encryption.reset") as reset,
        patch(
            "app.services.providers.has_encrypted_secrets",
            AsyncMock(return_value=False),
        ),
    ):
        key = await startup_env.ensure_encryption_key(dotenv)

    assert key == "generated-key"
    assert startup_env.settings.ENCRYPTION_KEY == "generated-key"
    assert dotenv.read_text() == "ENCRYPTION_KEY=generated-key\n"
    reset.assert_called_once_with()


@pytest.mark.asyncio
async def test_ensure_encryption_key_refuses_existing_encrypted_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(startup_env.settings, "ENCRYPTION_KEY", "")

    with (
        patch("app.services.encryption.is_encryption_enabled", return_value=False),
        patch(
            "app.services.providers.has_encrypted_secrets",
            AsyncMock(return_value=True),
        ),
    ):
        with pytest.raises(RuntimeError, match="database contains encrypted secrets"):
            await startup_env.ensure_encryption_key(tmp_path / ".env")

    assert not (tmp_path / ".env").exists()


def test_ensure_jwt_secret_generates_persists_and_configures_auth(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    configure = Mock(return_value="j" * 64)
    monkeypatch.setattr(startup_env.settings, "JWT_SECRET", "")
    monkeypatch.setattr(startup_env.secrets, "token_hex", lambda _n: "j" * 64)

    with patch("app.services.auth.configure_jwt_secret", configure):
        secret = startup_env.ensure_jwt_secret(dotenv)

    assert secret == "j" * 64
    assert startup_env.settings.JWT_SECRET == "j" * 64
    assert dotenv.read_text() == f"JWT_SECRET={'j' * 64}\n"
    configure.assert_called_once_with("j" * 64)


def test_ensure_jwt_secret_uses_existing_setting_without_dotenv_write(tmp_path, monkeypatch):
    dotenv = tmp_path / ".env"
    configure = Mock(return_value="configured-secret")
    monkeypatch.setattr(startup_env.settings, "JWT_SECRET", "configured-secret")

    with patch("app.services.auth.configure_jwt_secret", configure):
        secret = startup_env.ensure_jwt_secret(dotenv)

    assert secret == "configured-secret"
    assert not dotenv.exists()
    configure.assert_called_once_with("configured-secret")


def test_configured_jwt_secret_signs_new_tokens(monkeypatch):
    from app.services import auth

    monkeypatch.setattr(auth.settings, "JWT_SECRET", "")
    monkeypatch.setattr(auth, "_jwt_secret", "old-ephemeral")
    monkeypatch.setattr(auth, "_jwt_secret_is_ephemeral", True)
    monkeypatch.setattr(auth, "_jwt_secret_warning_logged", False)

    configured_secret = "k" * 64
    auth.configure_jwt_secret(configured_secret)
    token = auth.create_access_token(
        SimpleNamespace(
            id=uuid4(),
            email="user@example.com",
            display_name="User",
            is_admin=False,
        )
    )

    payload = jwt.decode(token, configured_secret, algorithms=["HS256"])
    assert payload["email"] == "user@example.com"
    assert auth._jwt_secret_is_ephemeral is False
