from __future__ import annotations

import pytest

from app.tools.local.memory_files import _resolve_memory_write_path


def test_resolve_memory_write_path_is_memory_rooted(tmp_path):
    resolved = _resolve_memory_write_path("reference/project", str(tmp_path))

    assert resolved == str(tmp_path / "reference" / "project.md")


def test_resolve_memory_write_path_accepts_memory_prefix(tmp_path):
    resolved = _resolve_memory_write_path("memory/logs/2026-04-29.md", str(tmp_path))

    assert resolved == str(tmp_path / "logs" / "2026-04-29.md")


def test_resolve_memory_write_path_rejects_escape(tmp_path):
    with pytest.raises(ValueError):
        _resolve_memory_write_path("../project/MEMORY.md", str(tmp_path))
