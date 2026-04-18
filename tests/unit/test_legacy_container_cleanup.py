"""Startup sweep that removes pre-multi-instance integration containers.

Before the multi-instance collision fix, `integrations/web_search` and
`integrations/wyoming` hard-coded daemon-global container names
(``spindrel-searxng``, ``spindrel-playwright``, ``spindrel-wyoming-*``).
Old orphan containers with those names would squat and block the new,
instance-scoped stacks. The first boot after the fix must remove them,
but only once — guarded by a `server_settings` row.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import (
    _LEGACY_CLEANUP_SETTING_KEY,
    _LEGACY_INTEGRATION_CONTAINER_NAMES,
    _legacy_integration_container_cleanup,
)


def _mk_subprocess(stdout: bytes, returncode: int = 0):
    proc = AsyncMock()
    proc.communicate.return_value = (stdout, b"")
    proc.returncode = returncode
    return proc


def _session_ctx_returning(initial_flag_value: str | None):
    """Build a fake async_session context manager.

    ``initial_flag_value`` is what the first SELECT returns (None means the
    flag row is missing). Merges are recorded on ``.merged`` for assertion.
    """
    db = AsyncMock()
    db.merged = []

    async def _execute(stmt):
        result = MagicMock()
        if initial_flag_value is None:
            result.scalar_one_or_none.return_value = None
        else:
            row = MagicMock()
            row.value = initial_flag_value
            result.scalar_one_or_none.return_value = row
        return result

    async def _merge(obj):
        db.merged.append(obj)

    db.execute = _execute
    db.merge = _merge
    db.commit = AsyncMock()

    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=db)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory, db


@pytest.mark.asyncio
async def test_skip_when_flag_already_set():
    factory, db = _session_ctx_returning("1")
    calls: list[tuple] = []

    async def _fake_exec(*cmd, **kwargs):
        calls.append(cmd)
        return _mk_subprocess(b"", returncode=0)

    with patch("app.db.engine.async_session", factory), \
         patch("asyncio.create_subprocess_exec", side_effect=_fake_exec):
        await _legacy_integration_container_cleanup()

    # Flag already set → no docker subprocess calls, no merge
    assert calls == []
    assert db.merged == []


@pytest.mark.asyncio
async def test_removes_unlabeled_orphan_and_sets_flag():
    # Simulate: docker inspect succeeds for one container (empty label), rm succeeds;
    # docker inspect fails (exit 1) for the rest (no such container).
    inspect_results = {
        "spindrel-searxng": (b"|created\n", 0),       # legacy, no stack-id label → remove
        "spindrel-playwright": (b"", 1),
        "spindrel-wyoming-whisper": (b"", 1),
        "spindrel-wyoming-piper": (b"", 1),
    }
    rm_calls: list[str] = []

    async def _fake_exec(*cmd, **kwargs):
        if cmd[:2] == ("docker", "inspect"):
            name = cmd[-1]
            stdout, rc = inspect_results.get(name, (b"", 1))
            return _mk_subprocess(stdout, returncode=rc)
        if cmd[:3] == ("docker", "rm", "-f"):
            rm_calls.append(cmd[-1])
            return _mk_subprocess(b"", returncode=0)
        return _mk_subprocess(b"", returncode=0)

    factory, db = _session_ctx_returning(None)

    with patch("app.db.engine.async_session", factory), \
         patch("asyncio.create_subprocess_exec", side_effect=_fake_exec):
        await _legacy_integration_container_cleanup()

    assert rm_calls == ["spindrel-searxng"]
    # One-shot flag recorded
    assert len(db.merged) == 1
    assert db.merged[0].key == _LEGACY_CLEANUP_SETTING_KEY
    assert db.merged[0].value == "1"


@pytest.mark.asyncio
async def test_labeled_container_is_left_alone():
    # A container with a com.docker.stack-id label belongs to a known stack
    # and must not be rm'd — the stack service will manage it.
    inspect_results = {
        "spindrel-searxng": (b"some-stack-uuid|running\n", 0),
        "spindrel-playwright": (b"", 1),
        "spindrel-wyoming-whisper": (b"", 1),
        "spindrel-wyoming-piper": (b"", 1),
    }
    rm_calls: list[str] = []

    async def _fake_exec(*cmd, **kwargs):
        if cmd[:2] == ("docker", "inspect"):
            name = cmd[-1]
            stdout, rc = inspect_results.get(name, (b"", 1))
            return _mk_subprocess(stdout, returncode=rc)
        if cmd[:3] == ("docker", "rm", "-f"):
            rm_calls.append(cmd[-1])
            return _mk_subprocess(b"", returncode=0)
        return _mk_subprocess(b"", returncode=0)

    factory, db = _session_ctx_returning(None)

    with patch("app.db.engine.async_session", factory), \
         patch("asyncio.create_subprocess_exec", side_effect=_fake_exec):
        await _legacy_integration_container_cleanup()

    assert rm_calls == []
    # Flag is still set so we don't rescan on every boot
    assert len(db.merged) == 1


def test_legacy_container_names_cover_expected_integrations():
    """Guardrail: if a future integration adds a new globally-named
    container, this list must grow to include it or first-boot will leak
    orphans. Surfaces the decision explicitly in review."""
    assert "spindrel-searxng" in _LEGACY_INTEGRATION_CONTAINER_NAMES
    assert "spindrel-playwright" in _LEGACY_INTEGRATION_CONTAINER_NAMES
    assert "spindrel-wyoming-whisper" in _LEGACY_INTEGRATION_CONTAINER_NAMES
    assert "spindrel-wyoming-piper" in _LEGACY_INTEGRATION_CONTAINER_NAMES
