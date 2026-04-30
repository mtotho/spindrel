"""Tests for app.services.integration_deps — auto-install on startup."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.integration_deps import (
    _check_npm_deps,
    _check_python_deps,
    _check_system_deps,
    _is_system_dep_available,
    ensure_integration_deps,
)


# ---------------------------------------------------------------------------
# Python deps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skips_when_all_python_deps_installed():
    """No subprocess call when every import succeeds."""
    deps = [{"package": "os", "import_name": "os"}]
    with patch("asyncio.create_subprocess_exec") as mock_exec:
        await _check_python_deps("test_int", deps, Path("/tmp/test"))
        mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_runs_pip_when_import_fails():
    """Calls pip install when an import raises ImportError."""
    deps = [{"package": "nonexistent_pkg_xyz", "import_name": "nonexistent_pkg_xyz"}]

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await _check_python_deps("test_int", deps, Path("/tmp/test"))
        mock_exec.assert_called_once()
        # Should try pip install with the package name (no requirements.txt)
        call_args = mock_exec.call_args[0]
        assert "pip" in call_args
        assert "nonexistent_pkg_xyz" in call_args


@pytest.mark.asyncio
async def test_installs_missing_packages_by_name(tmp_path):
    """Always installs the specific missing packages by name from YAML."""
    deps = [{"package": "some-pkg", "import_name": "nonexistent_pkg_xyz"}]

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await _check_python_deps("test_int", deps, tmp_path)
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0]
        assert "some-pkg" in call_args


@pytest.mark.asyncio
async def test_continues_on_pip_failure():
    """Pip failure is logged but does not raise."""
    deps = [{"package": "bad_pkg", "import_name": "nonexistent_pkg_xyz"}]

    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"error msg"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        # Should not raise
        await _check_python_deps("test_int", deps, Path("/tmp/test"))


# ---------------------------------------------------------------------------
# npm deps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skips_npm_when_check_path_exists(tmp_path):
    """No npm install when check_path exists."""
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()

    deps = [{"package": "foo", "check_path": "node_modules"}]

    with patch("asyncio.create_subprocess_exec") as mock_exec:
        await _check_npm_deps("test_int", deps, tmp_path)
        mock_exec.assert_not_called()


@pytest.mark.asyncio
async def test_runs_npm_when_check_path_missing(tmp_path):
    """Calls npm install when check_path doesn't exist."""
    deps = [{"package": "foo", "check_path": "node_modules", "local_install_dir": "scripts"}]

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await _check_npm_deps("test_int", deps, tmp_path)
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0]
        assert "npm" in call_args


@pytest.mark.asyncio
async def test_runs_npm_when_binary_below_minimum_version(tmp_path, monkeypatch):
    """An existing old CLI is not treated as installed forever."""
    from app.services import integration_deps

    old_binary = tmp_path / "codex"
    old_binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr(integration_deps.shutil, "which", lambda _binary: str(old_binary))

    deps = [{
        "package": "@openai/codex",
        "binary_name": "codex",
        "minimum_version": "0.128.0",
        "version_command": "codex --version",
    }]

    calls: list[tuple[str, ...]] = []

    def _make_proc(stdout=b"", returncode=0):
        proc = MagicMock()
        proc.returncode = returncode
        proc.communicate = AsyncMock(return_value=(stdout, b""))
        return proc

    def _router(*args, **kwargs):
        calls.append(tuple(str(arg) for arg in args))
        if args[0] == str(old_binary):
            return _make_proc(stdout=b"codex-cli 0.125.0\n")
        return _make_proc()

    with patch("asyncio.create_subprocess_exec", side_effect=_router):
        await _check_npm_deps("codex", deps, tmp_path)

    assert calls[0] == (str(old_binary), "--version")
    assert calls[1][:3] == ("npm", "install", "-g")
    assert "@openai/codex" in calls[1]


@pytest.mark.asyncio
async def test_skips_npm_when_binary_meets_minimum_version(tmp_path, monkeypatch):
    from app.services import integration_deps

    current_binary = tmp_path / "codex"
    current_binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr(integration_deps.shutil, "which", lambda _binary: str(current_binary))

    deps = [{
        "package": "@openai/codex",
        "binary_name": "codex",
        "minimum_version": "0.128.0",
        "version_command": "codex --version",
    }]

    calls: list[tuple[str, ...]] = []

    def _make_proc(stdout=b"", returncode=0):
        proc = MagicMock()
        proc.returncode = returncode
        proc.communicate = AsyncMock(return_value=(stdout, b""))
        return proc

    def _router(*args, **kwargs):
        calls.append(tuple(str(arg) for arg in args))
        return _make_proc(stdout=b"codex-cli 0.128.0\n")

    with patch("asyncio.create_subprocess_exec", side_effect=_router):
        await _check_npm_deps("codex", deps, tmp_path)

    assert calls == [(str(current_binary), "--version")]


def test_integration_catalog_marks_stale_npm_binary_uninstalled(tmp_path, monkeypatch):
    from app.services import integration_catalog

    old_binary = tmp_path / "codex"
    old_binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr(integration_catalog.shutil, "which", lambda _binary: str(old_binary))

    class _Proc:
        returncode = 0
        stdout = "codex-cli 0.125.0\n"
        stderr = ""

    monkeypatch.setattr(integration_catalog.subprocess, "run", lambda *args, **kwargs: _Proc())

    entry: dict = {}
    setup = {
        "npm_dependencies": [{
            "package": "@openai/codex",
            "binary_name": "codex",
            "minimum_version": "0.128.0",
            "version_command": "codex --version",
        }]
    }

    integration_catalog._apply_npm_dependencies(entry, tmp_path, setup)

    assert entry["npm_deps_installed"] is False
    assert entry["npm_dependencies"] == [{
        "package": "@openai/codex",
        "binary_name": "codex",
        "installed": False,
        "minimum_version": "0.128.0",
    }]


# ---------------------------------------------------------------------------
# System deps
# ---------------------------------------------------------------------------


def test_system_dep_not_available_when_missing():
    """Reports missing when binary doesn't exist."""
    dep = {"binary": "nonexistent_binary_xyz"}
    assert _is_system_dep_available(dep) is False


def test_system_dep_available_via_alternatives():
    """Finds the binary via alternatives list."""
    dep = {"binary": "nonexistent_xyz", "alternatives": ["python3"]}
    assert _is_system_dep_available(dep) is True


def test_system_dep_available_when_found():
    """Reports available when primary binary exists."""
    dep = {"binary": "python3"}
    assert _is_system_dep_available(dep) is True


@pytest.mark.asyncio
async def test_check_system_deps_logs_warning_for_uninstalled(caplog):
    """Logs a warning when a system dep is missing and was never installed."""
    deps = [{"binary": "nonexistent_binary_xyz", "install_hint": "apt-get install xyz"}]

    import logging
    with caplog.at_level(logging.WARNING), \
         patch("app.services.integration_deps._read_installed_system_packages", return_value=set()):
        await _check_system_deps("test_int", deps)
    assert "nonexistent_binary_xyz" in caplog.text
    assert "test_int" in caplog.text


@pytest.mark.asyncio
async def test_check_system_deps_reinstalls_previously_installed(caplog):
    """Re-installs a package that was previously installed (survived in persist file)."""
    deps = [{"binary": "nonexistent_xyz", "apt_package": "some-pkg"}]

    import logging
    with caplog.at_level(logging.INFO), \
         patch("app.services.integration_deps._read_installed_system_packages", return_value={"some-pkg"}), \
         patch("app.services.integration_deps.install_system_package", new_callable=AsyncMock, return_value=True) as mock_install:
        await _check_system_deps("test_int", deps)
    mock_install.assert_called_once_with("some-pkg")


# ---------------------------------------------------------------------------
# install_system_package — dpkg -x into persistent /opt/spindrel-pkg
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_install_system_package_idempotent_when_manifest_present(tmp_path, monkeypatch):
    """If the manifest for a package already exists, install is a no-op —
    this is what makes rebuilds skip the install entirely."""
    from app.services import integration_deps

    pkg_root = tmp_path / "spindrel-pkg"
    manifest_dir = pkg_root / ".extracted-manifest"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "chromium.list").write_text("usr/bin/chromium\n")
    monkeypatch.setattr(integration_deps, "_PKG_ROOT", pkg_root)

    with patch("asyncio.create_subprocess_exec") as mock_exec, \
         patch("app.services.integration_deps._read_installed_system_packages", return_value={"chromium"}), \
         patch("app.services.integration_deps._persist_installed_system_packages") as mock_persist:
        ok = await integration_deps.install_system_package("chromium")

    assert ok is True
    mock_exec.assert_not_called()  # no downloads, no extracts
    mock_persist.assert_not_called()  # already persisted


@pytest.mark.asyncio
async def test_install_system_package_downloads_and_extracts(tmp_path, monkeypatch):
    """First install: apt-get download + dpkg -x into /opt/spindrel-pkg +
    manifest file written. No call to `apt-get install`."""
    from app.services import integration_deps

    pkg_root = tmp_path / "spindrel-pkg"
    pkg_root.mkdir()
    monkeypatch.setattr(integration_deps, "_PKG_ROOT", pkg_root)

    archives = tmp_path / "archives"
    archives.mkdir()
    deb_path = archives / "gh_2.40.0_amd64.deb"
    deb_path.write_bytes(b"fake-deb")

    # Mock every subprocess call the install flow makes.
    calls: list[tuple[tuple, dict]] = []

    def _make_fake_proc(stdout=b"", returncode=0):
        proc = MagicMock()
        proc.returncode = returncode
        proc.communicate = AsyncMock(return_value=(stdout, b""))
        return proc

    def _router(*args, **kwargs):
        calls.append((args, kwargs))
        argv = list(args)
        # Skip sudo prefix if present.
        if argv and argv[0] in ("sudo", "-n"):
            while argv and argv[0] in ("sudo", "-n"):
                argv.pop(0)
        head = argv[0] if argv else ""
        if head == "apt-get" and "update" in argv:
            return _make_fake_proc()
        if head == "apt-cache" and "depends" in argv:
            # Simulate just the root package (no missing transitive deps).
            return _make_fake_proc(stdout=b"gh\n")
        if head == "dpkg-query":
            return _make_fake_proc(returncode=1)  # "not installed in base"
        if head == "apt-get" and "download" in argv:
            return _make_fake_proc()
        if head == "dpkg-deb" and "--contents" in argv:
            return _make_fake_proc(
                stdout=b"-rwxr-xr-x root/root 12345 2024-01-01 00:00 ./usr/bin/gh\n"
            )
        if head == "dpkg" and "-x" in argv:
            # Pretend it wrote files — create the binary to satisfy later checks.
            (pkg_root / "usr").mkdir(exist_ok=True)
            (pkg_root / "usr" / "bin").mkdir(exist_ok=True)
            (pkg_root / "usr" / "bin" / "gh").write_bytes(b"bin")
            return _make_fake_proc()
        return _make_fake_proc()

    # _download_deb looks in /var/cache/apt/archives — redirect via patching Path.
    # Easier: patch the function itself to return our fake deb_path.
    async def _fake_download(pkg):
        return deb_path

    with patch.object(integration_deps, "_download_deb", side_effect=_fake_download), \
         patch("asyncio.create_subprocess_exec", side_effect=_router), \
         patch("app.services.integration_deps._apt_get_update_if_stale", new=AsyncMock()), \
         patch("app.services.integration_deps._read_installed_system_packages", return_value=set()), \
         patch("app.services.integration_deps._persist_installed_system_packages") as mock_persist:
        ok = await integration_deps.install_system_package("gh")

    assert ok is True
    # Manifest was written to the persistent pkg root.
    manifest = pkg_root / ".extracted-manifest" / "gh.list"
    assert manifest.is_file()
    assert "usr/bin/gh" in manifest.read_text()
    # Persisted to the installed-packages set.
    mock_persist.assert_called_once()
    persisted = mock_persist.call_args[0][0]
    assert "gh" in persisted
    # No `apt-get install` anywhere.
    for args, _ in calls:
        argv = [a for a in args if a not in ("sudo", "-n")]
        if argv[:2] == ["apt-get", "install"]:
            pytest.fail(f"should not call `apt-get install` anymore: {args}")
