"""Unit tests for script_runner — helper generation + scratch dir lifecycle."""
import os

import pytest

from app.services.script_runner import (
    HELPER_FILENAME,
    SCRATCH_PARENT,
    SCRIPT_FILENAME,
    cleanup_scratch_dir,
    prepare_scratch_dir,
    write_script_files,
    _helper_source,
)


def test_helper_source_exposes_tools_proxy():
    src = _helper_source()
    # The helper must expose a ``tools`` object plus the ToolError class.
    assert "tools = _ToolsProxy()" in src
    assert "class ToolError" in src
    # It must read the env vars that shared_workspace.py injects.
    assert "AGENT_SERVER_URL" in src
    assert "AGENT_SERVER_API_KEY" in src
    # And it must POST to the internal endpoint, not the legacy /admin/tools/exec.
    assert "/api/v1/internal/tools/exec" in src


def test_helper_source_uses_only_stdlib():
    """The helper runs in whatever Python the workspace has — no third-party
    imports allowed because we can't guarantee `requests` is installed."""
    src = _helper_source()
    # Must use urllib.request, not requests/httpx (avoid dependency surprises).
    assert "import urllib.request" in src
    assert "import requests" not in src
    assert "import httpx" not in src


def test_prepare_scratch_dir_creates_unique_dirs(tmp_path):
    a = prepare_scratch_dir(str(tmp_path), "abc12345")
    b = prepare_scratch_dir(str(tmp_path), "abc12345")
    assert a != b
    assert a.is_dir()
    assert b.is_dir()
    assert (tmp_path / SCRATCH_PARENT).is_dir()
    # Correlation prefix shows up in the dir name when supplied.
    assert "abc12345" in a.name
    assert "abc12345" in b.name


def test_prepare_scratch_dir_without_correlation_id(tmp_path):
    d = prepare_scratch_dir(str(tmp_path), None)
    assert d.is_dir()
    # No correlation prefix when none was given.
    assert "-" not in d.name or len(d.name) <= 12


def test_write_script_files_drops_both_files(tmp_path):
    scratch = prepare_scratch_dir(str(tmp_path), None)
    user_script = "from spindrel import tools\nprint('hi')\n"
    script_path, helper_path = write_script_files(scratch, user_script)

    assert script_path.name == SCRIPT_FILENAME
    assert helper_path.name == HELPER_FILENAME
    assert script_path.read_text() == user_script
    # Helper text contains the proxy class.
    assert "_ToolsProxy" in helper_path.read_text()


def test_cleanup_scratch_dir_removes_dir(tmp_path):
    scratch = prepare_scratch_dir(str(tmp_path), None)
    write_script_files(scratch, "print('hi')")
    assert scratch.is_dir()
    cleanup_scratch_dir(scratch)
    assert not scratch.exists()


def test_cleanup_scratch_dir_swallows_missing_dir(tmp_path):
    scratch = tmp_path / "nonexistent"
    # Must not raise — the contract is best-effort.
    cleanup_scratch_dir(scratch)
