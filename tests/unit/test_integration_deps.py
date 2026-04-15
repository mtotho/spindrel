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
async def test_uses_requirements_txt_when_available(tmp_path):
    """Prefers requirements.txt when the file exists."""
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("some-pkg>=1.0\n")

    deps = [{"package": "some-pkg", "import_name": "nonexistent_pkg_xyz"}]

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await _check_python_deps("test_int", deps, tmp_path)
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0]
        assert "-r" in call_args
        assert str(req_file) in call_args


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


# ---------------------------------------------------------------------------
# System deps
# ---------------------------------------------------------------------------


def test_system_dep_logs_warning_when_missing(caplog):
    """Logs a warning when a system binary is not found."""
    deps = [{"binary": "nonexistent_binary_xyz", "install_hint": "apt-get install xyz"}]

    import logging
    with caplog.at_level(logging.WARNING):
        _check_system_deps("test_int", deps)
    assert "nonexistent_binary_xyz" in caplog.text
    assert "test_int" in caplog.text


def test_system_dep_checks_alternatives():
    """Finds the binary via alternatives list."""
    deps = [{"binary": "nonexistent_xyz", "alternatives": ["python3"], "install_hint": ""}]

    import logging
    import io
    handler = logging.StreamHandler(io.StringIO())
    logger = logging.getLogger("app.services.integration_deps")
    logger.addHandler(handler)
    try:
        _check_system_deps("test_int", deps)
        # python3 exists, so no warning should be logged
        output = handler.stream.getvalue()
        assert "nonexistent_xyz" not in output
    finally:
        logger.removeHandler(handler)


def test_system_dep_no_warning_when_found():
    """No warning when the primary binary exists (python3 is always available)."""
    deps = [{"binary": "python3", "install_hint": ""}]

    import logging
    import io
    handler = logging.StreamHandler(io.StringIO())
    logger = logging.getLogger("app.services.integration_deps")
    logger.addHandler(handler)
    try:
        _check_system_deps("test_int", deps)
        output = handler.stream.getvalue()
        assert "python3" not in output
    finally:
        logger.removeHandler(handler)
