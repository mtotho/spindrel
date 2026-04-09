"""Unit tests for bot hooks service — path matching, cooldown, re-entrancy guard."""
import time
import uuid
from contextvars import copy_context
from unittest.mock import MagicMock

import pytest

from app.services.bot_hooks import (
    _matches_conditions,
    _find_matching_hooks,
    _check_cooldown,
    _hook_executing,
    _hooks_by_bot,
    _cooldowns,
)


def _make_hook(**overrides):
    """Create a mock BotHook with sensible defaults."""
    defaults = {
        "id": uuid.uuid4(),
        "bot_id": "test-bot",
        "name": "test-hook",
        "trigger": "before_access",
        "conditions": {"path": "/workspace/repos/vault/**"},
        "command": "cd /workspace/repos/vault && git pull",
        "cooldown_seconds": 60,
        "on_failure": "block",
        "enabled": True,
    }
    defaults.update(overrides)
    hook = MagicMock()
    for k, v in defaults.items():
        setattr(hook, k, v)
    return hook


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset in-memory state before/after each test."""
    saved_hooks = dict(_hooks_by_bot)
    saved_cooldowns = dict(_cooldowns)
    _hooks_by_bot.clear()
    _cooldowns.clear()
    yield
    _hooks_by_bot.clear()
    _hooks_by_bot.update(saved_hooks)
    _cooldowns.clear()
    _cooldowns.update(saved_cooldowns)


class TestMatchesConditions:
    def test_glob_match(self):
        hook = _make_hook(conditions={"path": "/workspace/repos/vault/**"})
        assert _matches_conditions(hook, "/workspace/repos/vault/notes/today.md") is True

    def test_glob_no_match(self):
        hook = _make_hook(conditions={"path": "/workspace/repos/vault/**"})
        assert _matches_conditions(hook, "/workspace/repos/other/file.txt") is False

    def test_exact_path(self):
        hook = _make_hook(conditions={"path": "/workspace/repos/vault/README.md"})
        assert _matches_conditions(hook, "/workspace/repos/vault/README.md") is True
        assert _matches_conditions(hook, "/workspace/repos/vault/other.md") is False

    def test_wildcard_star(self):
        hook = _make_hook(conditions={"path": "/workspace/repos/*"})
        assert _matches_conditions(hook, "/workspace/repos/vault") is True
        assert _matches_conditions(hook, "/workspace/repos/other") is True

    def test_empty_conditions_matches_all(self):
        hook = _make_hook(conditions={})
        assert _matches_conditions(hook, "/workspace/anything") is True

    def test_none_conditions_matches_all(self):
        hook = _make_hook(conditions=None)
        assert _matches_conditions(hook, "/workspace/anything") is True

    def test_unknown_condition_key_no_match(self):
        hook = _make_hook(conditions={"tool": "exec_command"})
        assert _matches_conditions(hook, "/workspace/repos/vault/file.md") is False


class TestFindMatchingHooks:
    def test_finds_matching_hook(self):
        hook = _make_hook()
        _hooks_by_bot["test-bot"] = [hook]
        result = _find_matching_hooks("test-bot", "before_access", "/workspace/repos/vault/file.md")
        assert len(result) == 1
        assert result[0] is hook

    def test_no_hooks_for_bot(self):
        result = _find_matching_hooks("no-such-bot", "before_access", "/workspace/repos/vault/file.md")
        assert result == []

    def test_wrong_trigger(self):
        hook = _make_hook(trigger="after_write")
        _hooks_by_bot["test-bot"] = [hook]
        result = _find_matching_hooks("test-bot", "before_access", "/workspace/repos/vault/file.md")
        assert result == []

    def test_path_no_match(self):
        hook = _make_hook(conditions={"path": "/workspace/repos/other/**"})
        _hooks_by_bot["test-bot"] = [hook]
        result = _find_matching_hooks("test-bot", "before_access", "/workspace/repos/vault/file.md")
        assert result == []

    def test_re_entrancy_guard(self):
        hook = _make_hook()
        _hooks_by_bot["test-bot"] = [hook]

        # Simulate being inside a hook execution
        token = _hook_executing.set(True)
        try:
            result = _find_matching_hooks("test-bot", "before_access", "/workspace/repos/vault/file.md")
            assert result == []
        finally:
            _hook_executing.reset(token)

    def test_multiple_hooks_matched(self):
        hook1 = _make_hook(name="hook1")
        hook2 = _make_hook(name="hook2", trigger="before_access")
        _hooks_by_bot["test-bot"] = [hook1, hook2]
        result = _find_matching_hooks("test-bot", "before_access", "/workspace/repos/vault/file.md")
        assert len(result) == 2


class TestCooldown:
    def test_first_call_allowed(self):
        hook = _make_hook(cooldown_seconds=60)
        assert _check_cooldown(hook) is True

    def test_second_call_within_cooldown_blocked(self):
        hook = _make_hook(cooldown_seconds=60)
        _check_cooldown(hook)  # first call
        assert _check_cooldown(hook) is False

    def test_call_after_cooldown_allowed(self):
        hook = _make_hook(cooldown_seconds=0)
        _check_cooldown(hook)  # first call
        # With cooldown=0, next call is immediately allowed
        assert _check_cooldown(hook) is True

    def test_cooldown_is_per_hook(self):
        hook1 = _make_hook(id=uuid.uuid4(), cooldown_seconds=60)
        hook2 = _make_hook(id=uuid.uuid4(), cooldown_seconds=60)
        _check_cooldown(hook1)
        # hook2 should still be allowed
        assert _check_cooldown(hook2) is True
        # hook1 should be blocked
        assert _check_cooldown(hook1) is False
