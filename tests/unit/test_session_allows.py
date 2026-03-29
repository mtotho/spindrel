"""Tests for the session-scoped tool allow system."""
import time
from unittest.mock import patch

from app.agent.session_allows import (
    _allows,
    active_count,
    add_session_allow,
    cleanup_stale,
    clear_session,
    is_session_allowed,
)


def _reset():
    _allows.clear()


def test_add_and_check():
    _reset()
    assert not is_session_allowed("corr-1", "exec_command")
    add_session_allow("corr-1", "exec_command")
    assert is_session_allowed("corr-1", "exec_command")
    assert not is_session_allowed("corr-1", "read_file")
    assert not is_session_allowed("corr-2", "exec_command")
    _reset()


def test_none_correlation_id():
    _reset()
    assert not is_session_allowed(None, "exec_command")
    _reset()


def test_clear_session():
    _reset()
    add_session_allow("corr-1", "exec_command")
    add_session_allow("corr-1", "read_file")
    add_session_allow("corr-2", "exec_command")
    assert active_count() == 3
    removed = clear_session("corr-1")
    assert removed == 2
    assert not is_session_allowed("corr-1", "exec_command")
    assert is_session_allowed("corr-2", "exec_command")
    assert active_count() == 1
    _reset()


def test_clear_nonexistent_session():
    _reset()
    removed = clear_session("nonexistent")
    assert removed == 0
    _reset()


def test_cleanup_stale():
    _reset()
    # Manually insert a stale entry
    _allows[("old-corr", "tool_a")] = time.monotonic() - 20000
    add_session_allow("fresh-corr", "tool_b")
    assert active_count() == 2
    cleaned = cleanup_stale()
    assert cleaned == 1
    assert active_count() == 1
    assert is_session_allowed("fresh-corr", "tool_b")
    assert not is_session_allowed("old-corr", "tool_a")
    _reset()


def test_multiple_tools_same_session():
    _reset()
    add_session_allow("corr-1", "exec_command")
    add_session_allow("corr-1", "read_file")
    add_session_allow("corr-1", "write_file")
    assert active_count() == 3
    assert is_session_allowed("corr-1", "exec_command")
    assert is_session_allowed("corr-1", "read_file")
    assert is_session_allowed("corr-1", "write_file")
    assert not is_session_allowed("corr-1", "delete_file")
    _reset()
