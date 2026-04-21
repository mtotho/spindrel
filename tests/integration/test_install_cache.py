"""Integration tests for /admin/install-cache endpoints."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from .conftest import AUTH_HEADERS


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    """Redirect HOME_PATH to a writable tmp dir with seed content."""
    from app.routers.api_v1_admin import install_cache

    home = tmp_path / "home-spindrel"
    home.mkdir()
    (home / ".local").mkdir()
    (home / ".local" / "bin").mkdir()
    (home / ".local" / "bin" / "claude").write_bytes(b"x" * 1024)
    (home / ".cache").mkdir()
    (home / ".cache" / "pip").mkdir()
    (home / ".cache" / "pip" / "wheel.whl").write_bytes(b"y" * 2048)
    (home / ".bashrc").write_text("# test")

    monkeypatch.setattr(install_cache, "HOME_PATH", home)
    return home


@pytest.fixture
def tmp_apt(tmp_path, monkeypatch):
    """Redirect APT_PATH to a writable tmp dir with seed .deb files."""
    from app.routers.api_v1_admin import install_cache

    apt = tmp_path / "apt-archives"
    apt.mkdir()
    (apt / "partial").mkdir()
    (apt / "lock").write_bytes(b"")
    (apt / "foo_1.0_amd64.deb").write_bytes(b"d" * 4096)
    (apt / "bar_2.0_amd64.deb").write_bytes(b"e" * 8192)

    monkeypatch.setattr(install_cache, "APT_PATH", apt)
    return apt


@pytest.fixture
def tmp_pkg(tmp_path, monkeypatch):
    """Redirect PKG_PATH to a writable tmp dir with a seed extracted package."""
    from app.routers.api_v1_admin import install_cache

    pkg = tmp_path / "spindrel-pkg"
    pkg.mkdir()
    (pkg / "usr").mkdir()
    (pkg / "usr" / "bin").mkdir()
    (pkg / "usr" / "bin" / "chromium").write_bytes(b"z" * 16384)
    (pkg / "usr" / "lib").mkdir()
    (pkg / "usr" / "lib" / "libchrome.so").write_bytes(b"w" * 32768)
    (pkg / ".extracted-manifest").mkdir()
    (pkg / ".extracted-manifest" / "chromium.list").write_text(
        "usr/bin/chromium\nusr/lib/libchrome.so\n"
    )

    monkeypatch.setattr(install_cache, "PKG_PATH", pkg)
    return pkg


@pytest.mark.asyncio
async def test_install_cache_stats(client, tmp_home, tmp_apt, tmp_pkg):
    resp = await client.get("/api/v1/admin/install-cache", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["home_exists"] is True
    assert data["apt_exists"] is True
    assert data["pkg_exists"] is True
    # 1024 + 2048 for home seed
    assert data["home_bytes"] >= 3072
    # 4096 + 8192 for apt seed (lock is empty)
    assert data["apt_bytes"] >= 12288
    # 16384 + 32768 + manifest for pkg seed
    assert data["pkg_bytes"] >= 49152
    assert data["home_path"] == str(tmp_home)
    assert data["apt_path"] == str(tmp_apt)
    assert data["pkg_path"] == str(tmp_pkg)


@pytest.mark.asyncio
async def test_install_cache_clear_home_only(client, tmp_home, tmp_apt, tmp_pkg):
    resp = await client.post(
        "/api/v1/admin/install-cache/clear",
        headers=AUTH_HEADERS,
        json={"target": "home"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["cleared"] == ["home"]
    assert data["freed_bytes"] >= 3072
    assert data["errors"] == []

    # Dir itself preserved; skeleton recreated; seed content gone.
    assert tmp_home.exists()
    assert (tmp_home / ".local" / "bin").is_dir()
    assert (tmp_home / ".cache").is_dir()
    assert not (tmp_home / ".local" / "bin" / "claude").exists()
    assert not (tmp_home / ".cache" / "pip" / "wheel.whl").exists()
    assert not (tmp_home / ".bashrc").exists()

    # Apt + pkg untouched.
    assert (tmp_apt / "foo_1.0_amd64.deb").exists()
    assert (tmp_pkg / "usr" / "bin" / "chromium").exists()


@pytest.mark.asyncio
async def test_install_cache_clear_pkg_only(client, tmp_home, tmp_apt, tmp_pkg):
    """Clearing pkg removes extracted binaries but leaves the mount point."""
    resp = await client.post(
        "/api/v1/admin/install-cache/clear",
        headers=AUTH_HEADERS,
        json={"target": "pkg"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["cleared"] == ["pkg"]
    assert data["freed_bytes"] >= 49152
    assert data["errors"] == []

    # Mount point preserved; contents gone.
    assert tmp_pkg.exists()
    assert not (tmp_pkg / "usr").exists()
    assert not (tmp_pkg / ".extracted-manifest").exists()

    # Home + apt untouched.
    assert (tmp_home / ".bashrc").exists()
    assert (tmp_apt / "foo_1.0_amd64.deb").exists()


@pytest.mark.asyncio
async def test_install_cache_clear_apt_invokes_apt_get_clean(client, tmp_home, tmp_apt, tmp_pkg):
    """Apt branch must shell out to `apt-get clean`; we mock the subprocess."""
    def _fake_wipe_apt():
        for p in tmp_apt.glob("*.deb"):
            p.unlink()

    async def _fake_communicate(*_args, **_kwargs):
        _fake_wipe_apt()
        return (b"", b"")

    fake_proc = MagicMock()
    fake_proc.communicate = _fake_communicate
    fake_proc.returncode = 0

    with patch(
        "app.routers.api_v1_admin.install_cache.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_proc),
    ) as create_proc:
        resp = await client.post(
            "/api/v1/admin/install-cache/clear",
            headers=AUTH_HEADERS,
            json={"target": "apt"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["cleared"] == ["apt"]
    assert data["freed_bytes"] >= 12288
    assert data["errors"] == []

    # apt-get clean was invoked
    assert create_proc.call_count == 1
    args = create_proc.call_args[0]
    assert "apt-get" in args
    assert "clean" in args

    # Home + pkg untouched.
    assert (tmp_home / ".local" / "bin" / "claude").exists()
    assert (tmp_pkg / "usr" / "bin" / "chromium").exists()


@pytest.mark.asyncio
async def test_install_cache_clear_all_default(client, tmp_home, tmp_apt, tmp_pkg):
    """POST with no body defaults to target=all."""
    async def _fake_communicate(*_args, **_kwargs):
        for p in tmp_apt.glob("*.deb"):
            p.unlink()
        return (b"", b"")

    fake_proc = MagicMock()
    fake_proc.communicate = _fake_communicate
    fake_proc.returncode = 0

    with patch(
        "app.routers.api_v1_admin.install_cache.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_proc),
    ):
        resp = await client.post(
            "/api/v1/admin/install-cache/clear",
            headers=AUTH_HEADERS,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["cleared"] == ["pkg", "home", "apt"]
    assert not (tmp_home / ".bashrc").exists()
    assert not any(tmp_apt.glob("*.deb"))
    assert not (tmp_pkg / "usr").exists()


@pytest.mark.asyncio
async def test_install_cache_requires_admin_scope(client, tmp_home, tmp_apt, tmp_pkg):
    """A non-admin-scoped bearer must be rejected."""
    import uuid
    from app.dependencies import ApiKeyAuth, verify_auth_or_user

    app = client._transport.app  # type: ignore[attr-defined]

    async def _readonly_auth():
        return ApiKeyAuth(
            key_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            scopes=["storage:read"],
            name="readonly",
        )

    app.dependency_overrides[verify_auth_or_user] = _readonly_auth
    try:
        resp = await client.get(
            "/api/v1/admin/install-cache",
            headers={"Authorization": "Bearer readonly-key"},
        )
    finally:
        app.dependency_overrides.pop(verify_auth_or_user, None)

    assert resp.status_code == 403
